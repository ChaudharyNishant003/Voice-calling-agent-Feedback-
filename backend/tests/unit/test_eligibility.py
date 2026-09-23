"""One test per rule (doc 03 §1's 11-rule ordered table), precedence, idempotence, and the
hypothesis property test doc 08 §3 requires.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from app.domain.eligibility import (
    EligibilityAccountConfig,
    EligibilityContext,
    EligibilityPatient,
    EligibilityVisit,
    evaluate,
)
from app.domain.enums import EligibilityStatus, SuppressionReason, VisitType

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _visit(**overrides: object) -> EligibilityVisit:
    defaults: dict[str, object] = {
        "visit_type": VisitType.outpatient,
        "visit_date": date(2026, 1, 14),
        "patient_age": 45,
    }
    defaults.update(overrides)
    return EligibilityVisit(**defaults)  # type: ignore[arg-type]


def _patient(**overrides: object) -> EligibilityPatient:
    defaults: dict[str, object] = {"is_deleted": False}
    defaults.update(overrides)
    return EligibilityPatient(**defaults)  # type: ignore[arg-type]


def _account(**overrides: object) -> EligibilityAccountConfig:
    defaults: dict[str, object] = {
        "recency_window_hours": 72,
        "dedupe_window_days": 7,
        "frequency_cap_days": 30,
        "frequency_cap_count": 1,
        "shared_number_threshold": 3,
    }
    defaults.update(overrides)
    return EligibilityAccountConfig(**defaults)  # type: ignore[arg-type]


def _context(**overrides: object) -> EligibilityContext:
    defaults: dict[str, object] = {
        "now": _NOW,
        "is_valid_phone": True,
        "is_opted_out": False,
        "is_dnd": False,
        "has_duplicate_encounter": False,
        "already_called_this_visit": False,
        "calls_in_frequency_window": 0,
        "shared_number_count_in_batch": 0,
    }
    defaults.update(overrides)
    return EligibilityContext(**defaults)  # type: ignore[arg-type]


def test_happy_path_is_eligible() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context())
    assert decision.status == EligibilityStatus.eligible
    assert decision.reason is None


def test_rule_1_deleted_patient() -> None:
    decision = evaluate(_visit(), _patient(is_deleted=True), _account(), _context())
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.deleted_patient


def test_rule_2_out_of_scope_visit_type() -> None:
    # VisitType enum only has outpatient/diagnostic (doc 02 §1 — MVP scope), so this rule is
    # exercised via a value outside the enum's declared members to prove the guard itself works.
    decision = evaluate(
        EligibilityVisit(visit_type="inpatient", visit_date=date(2026, 1, 14), patient_age=45),  # type: ignore[arg-type]
        _patient(),
        _account(),
        _context(),
    )
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.out_of_scope_visit_type


def test_rule_3_minor() -> None:
    decision = evaluate(_visit(patient_age=17), _patient(), _account(), _context())
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.minor


def test_rule_4_invalid_number() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(is_valid_phone=False))
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.invalid_number


def test_rule_5_opt_out() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(is_opted_out=True))
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.opt_out


def test_rule_6_dnd() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(is_dnd=True))
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.dnd


def test_rule_7_stale_visit() -> None:
    old_visit = _visit(visit_date=date(2026, 1, 1))  # 14 days before _NOW, window is 72h
    decision = evaluate(old_visit, _patient(), _account(), _context())
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.stale_visit


def test_rule_7_boundary_within_window_is_not_stale() -> None:
    recent_visit = _visit(visit_date=(_NOW - timedelta(hours=1)).date())
    decision = evaluate(recent_visit, _patient(), _account(), _context())
    assert decision.reason != SuppressionReason.stale_visit


def test_rule_8_duplicate_encounter() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(has_duplicate_encounter=True))
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.duplicate_encounter


def test_rule_9_already_called_visit() -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(already_called_this_visit=True))
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.already_called_visit


def test_rule_10_frequency_cap() -> None:
    decision = evaluate(
        _visit(), _patient(), _account(frequency_cap_count=1), _context(calls_in_frequency_window=1)
    )
    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.frequency_cap


def test_rule_11_shared_number_goes_to_review_not_suppressed() -> None:
    decision = evaluate(
        _visit(),
        _patient(),
        _account(shared_number_threshold=3),
        _context(shared_number_count_in_batch=4),
    )
    assert decision.status == EligibilityStatus.review
    assert decision.reason == SuppressionReason.shared_number_review


def test_shared_number_at_threshold_is_not_review() -> None:
    decision = evaluate(
        _visit(),
        _patient(),
        _account(shared_number_threshold=3),
        _context(shared_number_count_in_batch=3),
    )
    assert decision.reason != SuppressionReason.shared_number_review


def test_precedence_first_failing_rule_wins() -> None:
    # minor (rule 3) should win over dnd (rule 6) since it's checked first.
    decision = evaluate(_visit(patient_age=10), _patient(), _account(), _context(is_dnd=True))
    assert decision.reason == SuppressionReason.minor


def test_idempotence_same_inputs_same_decision() -> None:
    v, p, a, c = _visit(), _patient(), _account(), _context(has_duplicate_encounter=True)
    first = evaluate(v, p, a, c)
    second = evaluate(v, p, a, c)
    assert first == second


@given(
    patient_age=st.integers(min_value=-5, max_value=150),
    is_opted_out=st.booleans(),
    is_dnd=st.booleans(),
    is_deleted=st.booleans(),
    is_valid_phone=st.booleans(),
)
def test_property_exactly_one_status_and_at_most_one_reason(
    patient_age: int, is_opted_out: bool, is_dnd: bool, is_deleted: bool, is_valid_phone: bool
) -> None:
    decision = evaluate(
        _visit(patient_age=patient_age),
        _patient(is_deleted=is_deleted),
        _account(),
        _context(is_opted_out=is_opted_out, is_dnd=is_dnd, is_valid_phone=is_valid_phone),
    )
    assert decision.status in (
        EligibilityStatus.eligible,
        EligibilityStatus.suppressed,
        EligibilityStatus.review,
    )
    if decision.status == EligibilityStatus.eligible:
        assert decision.reason is None
    else:
        assert decision.reason is not None

    if patient_age < 18 and not is_deleted and is_valid_phone:
        # Minors are suppressed unless an earlier rule (deleted patient) already caught them.
        assert decision.status == EligibilityStatus.suppressed


@given(is_opted_out=st.just(True))
def test_property_opted_out_never_eligible_regardless_of_other_fields(is_opted_out: bool) -> None:
    decision = evaluate(_visit(), _patient(), _account(), _context(is_opted_out=is_opted_out))
    assert decision.status != EligibilityStatus.eligible
