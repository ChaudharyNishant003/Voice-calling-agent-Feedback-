from __future__ import annotations

import tempfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.errors import AuthError
from app.core.security import (
    hash_password,
    hash_refresh_token,
    issue_access_token,
    load_or_create_jwt_keys,
    verify_access_token,
    verify_password,
)
from app.domain.enums import UserRole


def test_hash_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple 9!")
    assert verify_password("correct horse battery staple 9!", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple 9!")
    assert not verify_password("wrong password entirely", hashed)


def test_hash_password_is_salted_nondeterministic() -> None:
    a = hash_password("same password same password")
    b = hash_password("same password same password")
    assert a != b


def test_load_or_create_jwt_keys_generates_when_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "jwt_ed25519")
        private_key, public_key, kid = load_or_create_jwt_keys(path, allow_generate=True)
        assert Path(path).exists()
        assert len(kid) == 16

        # Loading again reads the same persisted key (same kid), doesn't regenerate.
        _private2, _public2, kid2 = load_or_create_jwt_keys(path, allow_generate=True)
        assert kid2 == kid


def test_load_or_create_jwt_keys_refuses_when_missing_and_generation_disabled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "jwt_ed25519")
        with pytest.raises(RuntimeError, match="auto-generation is disabled"):
            load_or_create_jwt_keys(path, allow_generate=False)


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "jwt_ed25519")
        private_key, _public_key, kid = load_or_create_jwt_keys(path, allow_generate=True)
        return private_key, kid


def test_issue_and_verify_access_token_roundtrip() -> None:
    private_key, kid = _keypair()
    public_key = private_key.public_key()
    token = issue_access_token(
        user_id="usr_abc123",
        account_id="acc_xyz789",
        role=UserRole.admin,
        private_key=private_key,
        kid=kid,
    )
    claims = verify_access_token(token, {kid: public_key})
    assert claims.user_id == "usr_abc123"
    assert claims.account_id == "acc_xyz789"
    assert claims.role == UserRole.admin


def test_verify_access_token_rejects_unknown_kid() -> None:
    private_key, kid = _keypair()
    public_key = private_key.public_key()
    token = issue_access_token(
        user_id="usr_1", account_id=None, role=UserRole.read_only, private_key=private_key, kid=kid
    )
    with pytest.raises(AuthError):
        verify_access_token(token, {"some-other-kid": public_key})


def test_verify_access_token_rejects_expired_token() -> None:
    private_key, kid = _keypair()
    public_key = private_key.public_key()
    token = issue_access_token(
        user_id="usr_1",
        account_id=None,
        role=UserRole.read_only,
        private_key=private_key,
        kid=kid,
        now=time.time() - 3600,  # issued an hour ago; 15 min TTL means long expired
    )
    with pytest.raises(AuthError):
        verify_access_token(token, {kid: public_key})


def test_verify_access_token_rejects_tampered_signature() -> None:
    private_key, kid = _keypair()
    other_private_key = Ed25519PrivateKey.generate()
    token = issue_access_token(
        user_id="usr_1", account_id=None, role=UserRole.read_only, private_key=private_key, kid=kid
    )
    # Re-sign the same payload with a different key but keep the original kid header — simulates a
    # forged token claiming to be from a key it wasn't actually signed by.
    payload = pyjwt.decode(token, options={"verify_signature": False})
    forged = pyjwt.encode(payload, other_private_key, algorithm="EdDSA", headers={"kid": kid})
    with pytest.raises(AuthError):
        verify_access_token(forged, {kid: private_key.public_key()})


def test_hash_refresh_token_is_deterministic_and_never_reveals_the_token() -> None:
    a = hash_refresh_token("some-opaque-refresh-token")
    b = hash_refresh_token("some-opaque-refresh-token")
    assert a == b
    assert b"some-opaque-refresh-token" not in a
