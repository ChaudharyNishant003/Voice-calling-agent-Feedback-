from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.audit_chain import canonical_json, compute_row_hash, verify_chain


@dataclass
class FakeRow:
    log_id: int
    prev_hash: bytes | None
    row_hash: bytes
    fields: dict[str, object] = field(default_factory=dict)

    def hashed_fields(self) -> dict[str, object]:
        return self.fields


def _chain(*field_sets: dict[str, object]) -> list[FakeRow]:
    rows: list[FakeRow] = []
    prev: bytes | None = None
    for i, fields in enumerate(field_sets, start=1):
        row_hash = compute_row_hash(prev, fields)
        rows.append(FakeRow(log_id=i, prev_hash=prev, row_hash=row_hash, fields=fields))
        prev = row_hash
    return rows


def test_canonical_json_is_stable_regardless_of_key_order() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b


def test_compute_row_hash_is_deterministic() -> None:
    row = {"action": "case.create", "created_at": datetime(2026, 1, 1, tzinfo=UTC)}
    assert compute_row_hash(None, row) == compute_row_hash(None, row)


def test_compute_row_hash_differs_on_prev_hash() -> None:
    row = {"action": "x"}
    assert compute_row_hash(None, row) != compute_row_hash(b"something", row)


def test_verify_chain_empty_is_intact() -> None:
    assert verify_chain([]) == []


def test_verify_chain_single_row_intact() -> None:
    rows = _chain({"action": "login"})
    assert verify_chain(rows) == []


def test_verify_chain_multiple_rows_intact() -> None:
    rows = _chain({"action": "a"}, {"action": "b"}, {"action": "c"})
    assert verify_chain(rows) == []


def test_verify_chain_detects_tampered_row_and_cascades_forward() -> None:
    rows = _chain({"action": "a"}, {"action": "b"}, {"action": "c"})
    rows[1].fields["action"] = "tampered"  # mutate stored content without recomputing row_hash

    # Tampering row 2 invalidates row 2 itself *and* row 3, since row 3 was built on row 2's real
    # (pre-tamper) hash, which the recomputed chain no longer produces.
    breaks = verify_chain(rows)
    assert [b.log_id for b in breaks] == [2, 3]


def test_verify_chain_detects_broken_link() -> None:
    rows = _chain({"action": "a"}, {"action": "b"})
    rows[1].prev_hash = b"wrong-prev-hash"

    breaks = verify_chain(rows)
    assert [b.log_id for b in breaks] == [2]


def test_verify_chain_tamper_cascades_to_later_rows() -> None:
    # Tampering row 1's content invalidates row 1's own hash *and* row 2's prev_hash expectation,
    # since row 2 was built on row 1's original (now-mismatched) row_hash.
    rows = _chain({"action": "a"}, {"action": "b"}, {"action": "c"})
    rows[0].fields["action"] = "tampered"

    breaks = verify_chain(rows)
    assert [b.log_id for b in breaks] == [1, 2, 3]
