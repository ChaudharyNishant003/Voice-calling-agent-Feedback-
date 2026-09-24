"""Crypto + auth primitives (docs/07_SECURITY_AND_COMPLIANCE.md §1-3). "Crypto lives only here —
no ad-hoc crypto elsewhere" (doc 07 §3): envelope AES-256-GCM encryption, password hashing, JWT
session tokens, and the RBAC permission map (doc 07 §1 names this file explicitly for that).

Every AES-GCM ciphertext is `nonce (12 bytes) || AES-GCM(ciphertext || 16-byte tag)`; the tag makes
tampering fail loudly (`cryptography.exceptions.InvalidTag`) instead of silently returning garbage.
This module only has the encryption *primitives* (generate/wrap/unwrap a DEK, encrypt/decrypt with
one) — fetching or storing an account's wrapped DEK is I/O and lives in
`db/repositories/encryption_keys.py`; likewise password/token *verification against the DB* lives
in `services/auth_service.py`, not here.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from app.core.config import get_settings
from app.core.errors import AuthError
from app.domain.enums import UserRole

_NONCE_LEN = 12
_KEY_LEN = 32  # AES-256

# ---------- Envelope encryption (docs/07 §3) ----------


def generate_dek() -> bytes:
    """A fresh random 256-bit data-encryption key."""
    return os.urandom(_KEY_LEN)


def load_kek_from_base64(value: str) -> bytes:
    """Decode `settings.local_kek_base64` into raw key bytes for `KMS_PROVIDER=local`."""
    kek = base64.b64decode(value)
    if len(kek) != _KEY_LEN:
        raise ValueError(f"KEK must decode to {_KEY_LEN} bytes, got {len(kek)}")
    return kek


def _aead_encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return nonce + ciphertext


def _aead_decrypt(blob: bytes, key: bytes) -> bytes:
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)


def wrap_dek(dek: bytes, kek: bytes) -> bytes:
    return _aead_encrypt(dek, kek)


def unwrap_dek(wrapped_dek: bytes, kek: bytes) -> bytes:
    return _aead_decrypt(wrapped_dek, kek)


def encrypt(plaintext: str, dek: bytes) -> bytes:
    return _aead_encrypt(plaintext.encode("utf-8"), dek)


def decrypt(ciphertext: bytes, dek: bytes) -> str:
    return _aead_decrypt(ciphertext, dek).decode("utf-8")


# ---------- Passwords (docs/07 §2 — argon2id m=64MB t=3 p=4) ----------

_password_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _password_hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False


# ---------- JWT sessions (docs/07 §2 — EdDSA access tokens, 15 min) ----------

ACCESS_TOKEN_TTL_S = 15 * 60


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: str
    account_id: str | None
    role: UserRole


def load_or_create_jwt_keys(
    path: str, *, allow_generate: bool
) -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Loads the Ed25519 keypair at `path` (PEM, PKCS8, unencrypted). If missing and
    `allow_generate` is true (non-production only — see `core/config.py`'s `validate_startup`),
    generates one and writes it there so it persists across restarts. In production a missing key
    is a hard boot failure, not an auto-fix.
    """
    key_path = Path(path)
    if key_path.exists():
        private_key = load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError(f"{path} does not contain an Ed25519 private key")
    elif allow_generate:
        private_key = Ed25519PrivateKey.generate()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(
            private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        )
    else:
        raise RuntimeError(f"JWT private key not found at {path} and auto-generation is disabled")

    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    kid = hashlib.sha256(public_bytes).hexdigest()[:16]
    return private_key, public_key, kid


@lru_cache
def get_jwt_keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Cached so the key file is only read/generated once per process. Callers needing to verify
    a token build `{kid: public_key}` from this (see `api/deps.py`) — only one active key exists
    yet, but `verify_access_token` already takes a dict so adding rotation later doesn't change
    its signature.
    """
    settings = get_settings()
    return load_or_create_jwt_keys(
        settings.jwt_private_key_path, allow_generate=settings.app_env != "production"
    )


def issue_access_token(
    *,
    user_id: str,
    account_id: str | None,
    role: UserRole,
    private_key: Ed25519PrivateKey,
    kid: str,
    now: float | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "account_id": account_id,
        "role": role.value,
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_TTL_S,
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA", headers={"kid": kid})


def verify_access_token(
    token: str, public_keys_by_kid: dict[str, Ed25519PublicKey]
) -> AccessTokenClaims:
    """Raises `AuthError("PFA-AUTH-002", ...)` on any failure (expired, bad signature, unknown
    `kid`, malformed) — from the caller's perspective these are all "session invalid, log in again"
    (doc 06 PFA-AUTH-002's handling), not distinct cases worth exposing differently.
    """
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        public_key = public_keys_by_kid.get(kid) if kid else None
        if public_key is None:
            raise AuthError(
                "PFA-AUTH-002", message="Your session has expired. Please sign in again."
            )

        claims = jwt.decode(token, public_key, algorithms=["EdDSA"])
    except jwt.PyJWTError as exc:
        raise AuthError(
            "PFA-AUTH-002", message="Your session has expired. Please sign in again.", cause=exc
        ) from exc

    return AccessTokenClaims(
        user_id=claims["sub"], account_id=claims.get("account_id"), role=UserRole(claims["role"])
    )


# ---------- Refresh tokens (docs/04 §1 / docs/07 §2 — opaque, hashed in DB) ----------


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


# ---------- RBAC permission map (docs/07 §1) ----------


class Permission(enum.StrEnum):
    view_queue_cases = "view_queue_cases"
    view_verbatim_transcript = "view_verbatim_transcript"
    play_audio = "play_audio"
    case_acknowledge_assign_resolve = "case_acknowledge_assign_resolve"
    case_close_reopen_merge_invalidate = "case_close_reopen_merge_invalidate"
    human_review_safety = "human_review_safety"
    upload_lists = "upload_lists"
    account_settings_users_survey = "account_settings_users_survey"
    pause_calling = "pause_calling"
    suppression_add_check = "suppression_add_check"
    deletion_request = "deletion_request"
    deletion_approve = "deletion_approve"
    audit_log = "audit_log"
    cost_dashboard = "cost_dashboard"


# doc 07 §1's table, row by row. Scoped caveats ("own depts" for dept_owner, "no verbatim" for
# read_only's queue view, "not own" for admin's deletion-approve) aren't expressible as a flat
# role->permission map — they're enforced in services, per doc 07 §1's own note ("scoped checks
# (dept/location) in services"). This map only answers "can this role ever do X at all."
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.super_admin: frozenset(
        {
            Permission.view_queue_cases,
            Permission.view_verbatim_transcript,
            Permission.play_audio,
            Permission.account_settings_users_survey,
            Permission.pause_calling,
            Permission.audit_log,
            Permission.cost_dashboard,
        }
    ),
    UserRole.admin: frozenset(
        {
            Permission.view_queue_cases,
            Permission.view_verbatim_transcript,
            Permission.play_audio,
            Permission.case_acknowledge_assign_resolve,
            Permission.case_close_reopen_merge_invalidate,
            Permission.human_review_safety,
            Permission.upload_lists,
            Permission.account_settings_users_survey,
            Permission.pause_calling,
            Permission.suppression_add_check,
            Permission.deletion_request,
            Permission.deletion_approve,
            Permission.audit_log,
            Permission.cost_dashboard,
        }
    ),
    UserRole.quality: frozenset(
        {
            Permission.view_queue_cases,
            Permission.view_verbatim_transcript,
            Permission.play_audio,
            Permission.case_acknowledge_assign_resolve,
            Permission.case_close_reopen_merge_invalidate,
            Permission.human_review_safety,
            Permission.upload_lists,
            Permission.pause_calling,
            Permission.suppression_add_check,
            Permission.deletion_request,
        }
    ),
    UserRole.dept_owner: frozenset(
        {
            Permission.view_queue_cases,  # own depts only — service-scoped
            Permission.view_verbatim_transcript,  # own depts only — service-scoped
            Permission.case_acknowledge_assign_resolve,  # own depts, ack/start/resolve only
        }
    ),
    UserRole.read_only: frozenset(
        {
            Permission.view_queue_cases,  # no verbatim — service-scoped
        }
    ),
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
