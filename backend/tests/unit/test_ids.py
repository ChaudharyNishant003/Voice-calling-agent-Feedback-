"""`core/ids.py` — prefixed id generation and formatting (doc 04 §1, CLAUDE.md §8)."""

from __future__ import annotations

import pytest

from app.core.ids import format_id, new_id, parse_id, uuid7


def test_new_id_has_correct_prefix() -> None:
    assert new_id("case").startswith("case_")
    assert new_id("account").startswith("acc_")
    assert new_id("user").startswith("usr_")


def test_new_id_is_unique_and_time_ordered() -> None:
    ids = [new_id("call") for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids)


def test_parse_id_roundtrip() -> None:
    generated = new_id("case")
    prefix, hex_part = parse_id(generated)
    assert prefix == "case"
    assert len(hex_part) == 32


def test_parse_id_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_id("not-a-valid-id")


def test_uuid7_is_version_7() -> None:
    assert uuid7().version == 7


def test_format_id_matches_new_id_shape_for_an_existing_uuid() -> None:
    existing = uuid7()
    formatted = format_id("account", existing)
    assert formatted == f"acc_{existing.hex}"
    prefix, hex_part = parse_id(formatted)
    assert prefix == "acc"
    assert hex_part == existing.hex


def test_format_id_falls_back_to_raw_entity_name_for_unknown_prefix() -> None:
    existing = uuid7()
    formatted = format_id("widget", existing)
    assert formatted == f"widget_{existing.hex}"
