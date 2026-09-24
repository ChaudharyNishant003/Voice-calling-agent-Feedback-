"""Pure per-row CSV validation for ingestion (docs/04_API_SPEC.md §4's CSV contract,
docs/06_ERROR_HANDLING_AND_MESSAGES.md PFA-ING-0xx).

Only validates what's computable from the row alone. `department`/`location_id` existence (doc 06
PFA-ING-014/018 — unknown department auto-creates + warns, unknown location hard-rejects) needs a DB
lookup against the account's rows, so this module only checks those two fields are *present*; the
service/worker layer (which has DB access) resolves them and applies those two codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from app.core.phone import InvalidPhoneNumber, normalize_e164
from app.domain.enums import VisitType

_MAX_DOCTOR_NAME_LEN = 80
_PATIENT_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")

_VISIT_TYPE_SYNONYMS = {
    "outpatient": VisitType.outpatient,
    "opd": VisitType.outpatient,
    "op": VisitType.outpatient,
    "diagnostic": VisitType.diagnostic,
    "lab": VisitType.diagnostic,
    "radiology": VisitType.diagnostic,
}

_TRUE_VALUES = {"true", "yes", "1"}
_FALSE_VALUES = {"false", "no", "0"}


@dataclass(frozen=True)
class RowIssue:
    """One row-level problem. `severity="error"` means the row is rejected (counts toward the
    `PFA-ING-003` threshold); `severity="warning"` means the row still proceeds with an adjusted
    field value (doc 06's "row-warn" codes: `PFA-ING-014`, `PFA-ING-015`).
    """

    row_number: int
    field: str | None
    code: str
    message: str
    severity: Literal["error", "warning"]


@dataclass(frozen=True)
class ValidatedRow:
    row_number: int
    external_patient_id: str
    phone_e164: str
    visit_date: date
    visit_type: VisitType
    department_raw: str
    doctor_name: str | None
    preferred_language: str | None
    patient_age: int
    consent_flag: bool | None
    location_external_id: str


@dataclass(frozen=True)
class RowValidationResult:
    row_number: int
    ok: bool
    row: ValidatedRow | None = None
    issues: tuple[RowIssue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")


REQUIRED_COLUMNS = frozenset(
    {
        "external_patient_id",
        "phone",
        "visit_date",
        "visit_type",
        "department",
        "patient_age",
        "location_id",
    }
)


def validate_row(
    row_number: int,
    raw: dict[str, str],
    *,
    account_languages: frozenset[str],
    date_format: Literal["YYYY-MM-DD", "DD-MM-YYYY"],
    today: date,
) -> RowValidationResult:
    issues: list[RowIssue] = []

    external_patient_id = _validate_patient_id(
        row_number, raw.get("external_patient_id", ""), issues
    )
    phone_e164 = _validate_phone(row_number, raw.get("phone", ""), issues)
    visit_date = _validate_visit_date(
        row_number, raw.get("visit_date", ""), date_format, today, issues
    )
    visit_type = _validate_visit_type(row_number, raw.get("visit_type", ""), issues)
    # `department`/`location_id` are required columns (doc 04 §4's "Req" ✅) but their doc-06 codes
    # (014/018) only cover the "value present but unrecognised" case — an *empty* cell has no
    # dedicated code, so a blank value here also uses that field's code, always as a hard error
    # regardless of that code's usual severity. Existence lookups (014's auto-create, 018's reject)
    # happen in the service layer, which has DB access this pure module doesn't.
    department_raw = _validate_required_text(
        row_number,
        raw.get("department", ""),
        field_name="department",
        code="PFA-ING-014",
        issues=issues,
    )
    doctor_name = _validate_doctor_name(raw.get("doctor_name"))
    preferred_language = _validate_language(
        row_number, raw.get("preferred_language"), account_languages, issues
    )
    patient_age = _validate_age(row_number, raw.get("patient_age", ""), issues)
    consent_flag = _validate_consent_flag(row_number, raw.get("consent_flag"), issues)
    location_external_id = _validate_required_text(
        row_number,
        raw.get("location_id", ""),
        field_name="location_id",
        code="PFA-ING-018",
        issues=issues,
    )

    if any(i.severity == "error" for i in issues):
        return RowValidationResult(row_number=row_number, ok=False, issues=tuple(issues))

    assert external_patient_id is not None
    assert phone_e164 is not None
    assert visit_date is not None
    assert visit_type is not None
    assert department_raw is not None
    assert patient_age is not None
    assert location_external_id is not None

    return RowValidationResult(
        row_number=row_number,
        ok=True,
        row=ValidatedRow(
            row_number=row_number,
            external_patient_id=external_patient_id,
            phone_e164=phone_e164,
            visit_date=visit_date,
            visit_type=visit_type,
            department_raw=department_raw,
            doctor_name=doctor_name,
            preferred_language=preferred_language,
            patient_age=patient_age,
            consent_flag=consent_flag,
            location_external_id=location_external_id,
        ),
        issues=tuple(issues),
    )


def _validate_patient_id(row_number: int, value: str, issues: list[RowIssue]) -> str | None:
    value = value.strip()
    if not (1 <= len(value) <= 64) or not set(value) <= _PATIENT_ID_ALLOWED:
        issues.append(
            RowIssue(
                row_number,
                "external_patient_id",
                "PFA-ING-010",
                f"Row {row_number}: patient ID is missing or has invalid characters.",
                "error",
            )
        )
        return None
    return value


def _validate_phone(row_number: int, value: str, issues: list[RowIssue]) -> str | None:
    try:
        return normalize_e164(value.strip())
    except InvalidPhoneNumber:
        issues.append(
            RowIssue(
                row_number,
                "phone",
                "PFA-ING-011",
                f"Row {row_number}: phone number is not a valid Indian number.",
                "error",
            )
        )
        return None


def _validate_visit_date(
    row_number: int,
    value: str,
    date_format: Literal["YYYY-MM-DD", "DD-MM-YYYY"],
    today: date,
    issues: list[RowIssue],
) -> date | None:
    fmt = "%Y-%m-%d" if date_format == "YYYY-MM-DD" else "%d-%m-%Y"
    try:
        parsed = datetime.strptime(value.strip(), fmt).date()
    except ValueError:
        parsed = None

    if parsed is None or parsed > today:
        issues.append(
            RowIssue(
                row_number,
                "visit_date",
                "PFA-ING-012",
                f"Row {row_number}: visit date must be a real past date ({date_format}).",
                "error",
            )
        )
        return None
    return parsed


def _validate_visit_type(row_number: int, value: str, issues: list[RowIssue]) -> VisitType | None:
    mapped = _VISIT_TYPE_SYNONYMS.get(value.strip().lower())
    if mapped is None:
        issues.append(
            RowIssue(
                row_number,
                "visit_type",
                "PFA-ING-013",
                f"Row {row_number}: visit type must be outpatient or diagnostic.",
                "error",
            )
        )
        return None
    return mapped


def _validate_required_text(
    row_number: int, value: str, *, field_name: str, code: str, issues: list[RowIssue]
) -> str | None:
    value = value.strip()
    if not value:
        issues.append(
            RowIssue(
                row_number,
                field_name,
                code,
                f"Row {row_number}: {field_name.replace('_', ' ')} is required.",
                "error",
            )
        )
        return None
    return value


def _validate_doctor_name(value: str | None) -> str | None:
    if not value:
        return None
    # Doc 06 has no error code for this field ("—") — silently truncate rather than reject.
    return value.strip()[:_MAX_DOCTOR_NAME_LEN] or None


def _validate_language(
    row_number: int, value: str | None, account_languages: frozenset[str], issues: list[RowIssue]
) -> str | None:
    if not value or not value.strip():
        return None
    code = value.strip().lower()
    if code not in account_languages:
        issues.append(
            RowIssue(
                row_number,
                "preferred_language",
                "PFA-ING-015",
                f"Row {row_number}: language '{value}' isn't enabled; we'll detect it on the call.",
                "warning",
            )
        )
        return None
    return code


def _validate_age(row_number: int, value: str, issues: list[RowIssue]) -> int | None:
    value = value.strip()
    try:
        age = int(value)
    except ValueError:
        age = None

    if age is None or not (0 <= age <= 130):
        issues.append(
            RowIssue(
                row_number,
                "patient_age",
                "PFA-ING-016",
                f"Row {row_number}: age must be a whole number.",
                "error",
            )
        )
        return None
    return age


def _validate_consent_flag(
    row_number: int, value: str | None, issues: list[RowIssue]
) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    issues.append(
        RowIssue(
            row_number,
            "consent_flag",
            "PFA-ING-017",
            f"Row {row_number}: consent flag must be yes/no.",
            "error",
        )
    )
    return None
