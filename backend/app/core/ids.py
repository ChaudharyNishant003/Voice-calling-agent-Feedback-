"""Time-ordered UUIDv7 primary keys, prefixed in API output (CLAUDE.md §8).

Prefixes: acc_ (account), loc_ (location), pat_ (patient), vis_ (visit), call_ (call), cmp_
(complaint), case_ (case), usr_ (user), req_ (request id, for error envelopes).
"""

from __future__ import annotations

import uuid6

PREFIXES = {
    "account": "acc",
    "location": "loc",
    "patient": "pat",
    "visit": "vis",
    "call": "call",
    "complaint": "cmp",
    "case": "case",
    "user": "usr",
    "req": "req",
}


def uuid7() -> uuid6.UUID:
    return uuid6.uuid7()


def new_id(entity: str) -> str:
    """Generate a prefixed, time-ordered id, e.g. new_id("case") -> "case_018f2c3a...".

    `entity` may be a key from PREFIXES ("case") or a raw prefix ("req") — both work so error
    envelopes (which aren't a modelled entity) can call new_id("req") directly.
    """
    prefix = PREFIXES.get(entity, entity)
    return f"{prefix}_{uuid7().hex}"


def parse_id(value: str) -> tuple[str, str]:
    """Split a prefixed id into (prefix, uuid_hex). Raises ValueError on malformed input."""
    prefix, _, hex_part = value.partition("_")
    if not hex_part or len(hex_part) != 32:
        raise ValueError(f"not a valid prefixed id: {value!r}")
    return prefix, hex_part
