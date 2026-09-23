"""Audit log tamper-evidence hashing (docs/07_SECURITY_AND_COMPLIANCE.md §6) — pure, no I/O.

`row_hash = SHA256(prev_hash || canonical_json(row))`. `row` excludes `log_id` (DB-assigned
identity, not payload — chain order comes from insertion sequence, not from hashing the sequence
number) and `row_hash` itself; `created_at` is included, so callers must set it explicitly in
application code rather than relying on the column's `server_default` (needed before insert, to
hash it) — see `app.services.audit_service`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


def canonical_json(row: Mapping[str, object]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def compute_row_hash(prev_hash: bytes | None, row: Mapping[str, object]) -> bytes:
    payload = (prev_hash or b"") + canonical_json(row).encode("utf-8")
    return hashlib.sha256(payload).digest()


class AuditRowLike(Protocol):
    log_id: int
    prev_hash: bytes | None
    row_hash: bytes

    def hashed_fields(self) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ChainBreak:
    log_id: int
    expected_hash: bytes
    stored_hash: bytes


def verify_chain(rows: Sequence[AuditRowLike]) -> list[ChainBreak]:
    """`rows` must be ordered by `log_id` ascending. Empty return means the chain is intact.

    Walks the chain carrying forward the *recomputed* expected hash (not each row's own stored
    `row_hash`) as the next row's expected `prev_hash`. This is what actually makes tampering
    detectable: recomputing each row's hash from only its own stored `prev_hash` (rather than the
    true running value) would only catch a row whose own `row_hash` was left stale after editing —
    it would miss the row entirely if an attacker also patched that row's `row_hash` to match its
    (now-also-edited) `prev_hash`, and it would never flag anything downstream. Cascading the
    *recomputed* value forward means editing row N invalidates row N (`row.prev_hash` and/or
    `row.row_hash` no longer matches the true history) and every row after it, which is the whole
    point of a hash chain.
    """
    breaks: list[ChainBreak] = []
    expected_prev: bytes | None = None
    for row in rows:
        expected_hash = compute_row_hash(expected_prev, row.hashed_fields())
        if row.prev_hash != expected_prev or row.row_hash != expected_hash:
            breaks.append(
                ChainBreak(log_id=row.log_id, expected_hash=expected_hash, stored_hash=row.row_hash)
            )
        expected_prev = expected_hash
    return breaks
