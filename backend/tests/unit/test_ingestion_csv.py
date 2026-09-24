"""Pure per-row CSV validation (docs/06_ERROR_HANDLING_AND_MESSAGES.md PFA-ING-01x,
docs/08_TESTING_STRATEGY.md §6 — "all row error codes").
"""

from __future__ import annotations

from datetime import date

from app.domain.ingestion_csv import RowValidationResult, validate_row

_TODAY = date(2026, 9, 24)
_LANGUAGES = frozenset({"en", "hi"})


def _valid_row(**overrides: str) -> dict[str, str]:
    row = {
        "external_patient_id": "PAT-001",
        "phone": "9876543210",
        "visit_date": "2026-09-20",
        "visit_type": "outpatient",
        "department": "cardiology",
        "doctor_name": "Dr. Rao",
        "preferred_language": "en",
        "patient_age": "45",
        "consent_flag": "yes",
        "location_id": "loc-1",
    }
    row.update(overrides)
    return row


def _validate(**overrides: str) -> RowValidationResult:
    return validate_row(
        2,
        _valid_row(**overrides),
        account_languages=_LANGUAGES,
        date_format="YYYY-MM-DD",
        today=_TODAY,
    )


def test_valid_row_passes_with_no_issues() -> None:
    result = _validate()
    assert result.ok
    assert result.row is not None
    assert result.row.external_patient_id == "PAT-001"
    assert result.row.phone_e164 == "+919876543210"
    assert result.row.visit_date == date(2026, 9, 20)
    assert result.row.patient_age == 45
    assert result.row.consent_flag is True
    assert not result.issues


def test_ing_010_bad_patient_id() -> None:
    result = _validate(external_patient_id="bad id with spaces!")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-010"


def test_ing_010_empty_patient_id() -> None:
    result = _validate(external_patient_id="")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-010"


def test_ing_011_bad_phone() -> None:
    result = _validate(phone="not-a-phone")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-011"


def test_ing_012_bad_date_format() -> None:
    result = _validate(visit_date="20-09-2026")  # wrong format for YYYY-MM-DD account setting
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-012"


def test_ing_012_future_date_rejected() -> None:
    result = _validate(visit_date="2099-01-01")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-012"


def test_ing_012_dd_mm_yyyy_account_format_accepted() -> None:
    result = validate_row(
        2,
        _valid_row(visit_date="20-09-2026"),
        account_languages=_LANGUAGES,
        date_format="DD-MM-YYYY",
        today=_TODAY,
    )
    assert result.ok
    assert result.row is not None
    assert result.row.visit_date == date(2026, 9, 20)


def test_ing_013_bad_visit_type() -> None:
    result = _validate(visit_type="surgery")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-013"


def test_ing_013_synonyms_are_mapped() -> None:
    for synonym in ("OPD", "op", "Lab", "radiology"):
        result = _validate(visit_type=synonym)
        assert result.ok, f"{synonym} should be a valid visit_type synonym"


def test_ing_014_empty_department_is_a_hard_error() -> None:
    result = _validate(department="")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-014"


def test_ing_015_unsupported_language_is_a_warning_not_a_rejection() -> None:
    result = _validate(preferred_language="fr")
    assert result.ok
    assert result.row is not None
    assert result.row.preferred_language is None  # ignored per doc 06
    assert result.warnings[0].code == "PFA-ING-015"


def test_ing_016_bad_age() -> None:
    result = _validate(patient_age="not-a-number")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-016"


def test_ing_016_age_out_of_range() -> None:
    result = _validate(patient_age="200")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-016"


def test_ing_017_bad_consent_flag() -> None:
    result = _validate(consent_flag="maybe")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-017"


def test_consent_flag_optional_and_accepts_multiple_spellings() -> None:
    for value, expected in (("yes", True), ("NO", False), ("1", True), ("0", False), ("", None)):
        result = _validate(consent_flag=value)
        assert result.ok, f"{value!r} should be a valid (or empty) consent flag"
        assert result.row is not None
        assert result.row.consent_flag is expected


def test_ing_018_empty_location_is_a_hard_error() -> None:
    result = _validate(location_id="")
    assert not result.ok
    assert result.errors[0].code == "PFA-ING-018"


def test_doctor_name_has_no_error_code_and_is_truncated_not_rejected() -> None:
    result = _validate(doctor_name="x" * 200)
    assert result.ok
    assert result.row is not None
    assert result.row.doctor_name is not None
    assert len(result.row.doctor_name) == 80


def test_multiple_errors_all_reported_on_one_row() -> None:
    result = _validate(phone="bad", patient_age="bad")
    assert not result.ok
    codes = {i.code for i in result.errors}
    assert "PFA-ING-011" in codes
    assert "PFA-ING-016" in codes
