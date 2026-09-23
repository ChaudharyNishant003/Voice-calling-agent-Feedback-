"""Envelope AES-256-GCM encryption primitives (docs/07_SECURITY_AND_COMPLIANCE.md §3).

Crypto lives only here — "no ad-hoc crypto elsewhere" (doc 07 §3). Every ciphertext is
`nonce (12 bytes) || AES-GCM(ciphertext || 16-byte tag)`; the tag makes tampering fail loudly
(`cryptography.exceptions.InvalidTag`) instead of silently returning garbage.

This module only has the primitives (generate/wrap/unwrap a DEK, encrypt/decrypt with one). Fetching
or storing an account's wrapped DEK is I/O and lives in `db/repositories/encryption_keys.py`.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12
_KEY_LEN = 32  # AES-256


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
