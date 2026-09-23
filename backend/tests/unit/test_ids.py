from app.core.ids import new_id, parse_id, uuid7


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
    import pytest

    with pytest.raises(ValueError):
        parse_id("not-a-valid-id")


def test_uuid7_is_version_7() -> None:
    assert uuid7().version == 7
