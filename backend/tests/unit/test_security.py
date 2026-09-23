import base64

import pytest
from cryptography.exceptions import InvalidTag

from app.core.security import (
    decrypt,
    encrypt,
    generate_dek,
    load_kek_from_base64,
    unwrap_dek,
    wrap_dek,
)


def test_generate_dek_is_32_bytes_and_random() -> None:
    a, b = generate_dek(), generate_dek()
    assert len(a) == 32
    assert len(b) == 32
    assert a != b


def test_load_kek_from_base64_roundtrip() -> None:
    raw = generate_dek()
    encoded = base64.b64encode(raw).decode()
    assert load_kek_from_base64(encoded) == raw


def test_load_kek_from_base64_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        load_kek_from_base64(base64.b64encode(b"too-short").decode())


def test_wrap_unwrap_dek_roundtrip() -> None:
    kek = generate_dek()
    dek = generate_dek()
    assert unwrap_dek(wrap_dek(dek, kek), kek) == dek


def test_unwrap_dek_with_wrong_kek_fails() -> None:
    dek = generate_dek()
    wrapped = wrap_dek(dek, generate_dek())
    with pytest.raises(InvalidTag):
        unwrap_dek(wrapped, generate_dek())


def test_encrypt_decrypt_roundtrip() -> None:
    dek = generate_dek()
    plaintext = "+919876543210"
    ciphertext = encrypt(plaintext, dek)
    assert plaintext.encode() not in ciphertext
    assert decrypt(ciphertext, dek) == plaintext


def test_decrypt_detects_tampering() -> None:
    dek = generate_dek()
    ciphertext = bytearray(encrypt("patient said the injection hurt", dek))
    ciphertext[-1] ^= 0xFF  # flip a bit in the auth tag
    with pytest.raises(InvalidTag):
        decrypt(bytes(ciphertext), dek)


def test_encrypt_is_nondeterministic_same_plaintext() -> None:
    dek = generate_dek()
    a = encrypt("hello", dek)
    b = encrypt("hello", dek)
    assert a != b  # random nonce per call
    assert decrypt(a, dek) == decrypt(b, dek) == "hello"
