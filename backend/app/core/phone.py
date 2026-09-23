"""Indian phone number normalisation + hashing.

CLAUDE.md §4 rule 8 (data minimisation): store `phone_hash` for matching; keep the encrypted
plaintext number only where dialling actually needs it. This module produces both, but never
logs either — `core.logging`'s redaction processor is the backstop if it ever leaks into a log call.
"""

from __future__ import annotations

import hashlib
import hmac

import phonenumbers
from phonenumbers import NumberParseException

DEFAULT_REGION = "IN"


class InvalidPhoneNumber(ValueError):
    pass


def normalize_e164(raw: str, region: str = DEFAULT_REGION) -> str:
    """Parse a phone number (with or without country code, spaces/dashes allowed) to E.164.

    Raises InvalidPhoneNumber if it isn't a valid, in-use number for the given region.
    """
    try:
        parsed = phonenumbers.parse(raw, region)
    except NumberParseException as exc:
        raise InvalidPhoneNumber(f"could not parse phone number: {raw!r}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumber(f"not a valid phone number: {raw!r}")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def phone_hash(e164: str, pepper: str) -> str:
    """HMAC-SHA256 of an E.164 number, for matching without storing/logging plaintext.

    `pepper` comes from settings.phone_hash_pepper (KMS-backed secret in production, never
    committed — see .env.example / docs/07_SECURITY_AND_COMPLIANCE.md).
    """
    if not pepper:
        raise ValueError("phone_hash requires a non-empty pepper")
    return hmac.new(pepper.encode("utf-8"), e164.encode("utf-8"), hashlib.sha256).hexdigest()
