import pytest

from app.core.phone import InvalidPhoneNumber, normalize_e164, phone_hash


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("0 98765-43210", "+919876543210"),
        ("+919876543210", "+919876543210"),
    ],
)
def test_normalize_e164_valid(raw: str, expected: str) -> None:
    assert normalize_e164(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "12345",
        "not a phone number",
        "",
        "0000000000",
    ],
)
def test_normalize_e164_invalid(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_e164(raw)


def test_phone_hash_deterministic_and_pepper_sensitive() -> None:
    e164 = "+919876543210"
    h1 = phone_hash(e164, pepper="pepper-a")
    h2 = phone_hash(e164, pepper="pepper-a")
    h3 = phone_hash(e164, pepper="pepper-b")

    assert h1 == h2
    assert h1 != h3
    assert e164 not in h1


def test_phone_hash_requires_pepper() -> None:
    with pytest.raises(ValueError):
        phone_hash("+919876543210", pepper="")
