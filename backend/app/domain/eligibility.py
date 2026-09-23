"""Eligibility engine (docs/03_CALL_FLOW_AND_CONVERSATION.md §1) — pure, no I/O.

`evaluate()` runs the 11 rules in the documented order; the first failing rule sets the reason, so
reports are stable. All I/O (suppression/dedupe/frequency/shared-number lookups) happens in
`app.services.eligibility_service`, which assembles `EligibilityContext` before calling this.

`consent_declined_visit` and `missing_required_field` (two `suppression_reason` values with no rule
in doc 03 §1's table) are deliberately not implemented here — see Open Question #22.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from app.domain.enums import EligibilityStatus, SuppressionReason, VisitType

_IN_SCOPE_VISIT_TYPES = frozenset({VisitType.outpatient, VisitType.diagnostic})


@dataclass(frozen=True)
class EligibilityVisit:
    visit_type: VisitType
    visit_date: date
    patient_age: int


@dataclass(frozen=True)
class EligibilityPatient:
    is_deleted: bool


@dataclass(frozen=True)
class EligibilityAccountConfig:
    recency_window_hours: int
    dedupe_window_days: int
    frequency_cap_days: int
    frequency_cap_count: int
    shared_number_threshold: int


@dataclass(frozen=True)
class EligibilityContext:
    """Every pre-computed I/O result the pure rules need — gathered by the service layer."""

    now: datetime
    is_valid_phone: bool
    is_opted_out: bool
    is_dnd: bool
    has_duplicate_encounter: bool
    already_called_this_visit: bool
    calls_in_frequency_window: int
    shared_number_count_in_batch: int


@dataclass(frozen=True)
class EligibilityDecision:
    status: EligibilityStatus
    reason: SuppressionReason | None


def _suppressed(reason: SuppressionReason) -> EligibilityDecision:
    return EligibilityDecision(status=EligibilityStatus.suppressed, reason=reason)


def evaluate(
    visit: EligibilityVisit,
    patient: EligibilityPatient,
    account: EligibilityAccountConfig,
    context: EligibilityContext,
) -> EligibilityDecision:
    if patient.is_deleted:
        return _suppressed(SuppressionReason.deleted_patient)

    if visit.visit_type not in _IN_SCOPE_VISIT_TYPES:
        return _suppressed(SuppressionReason.out_of_scope_visit_type)

    if visit.patient_age < 18:
        return _suppressed(SuppressionReason.minor)

    if not context.is_valid_phone:
        return _suppressed(SuppressionReason.invalid_number)

    if context.is_opted_out:
        return _suppressed(SuppressionReason.opt_out)

    if context.is_dnd:
        return _suppressed(SuppressionReason.dnd)

    # Only a date (no time) is captured at ingestion, so the visit is treated as occurring at
    # 00:00 UTC on visit_date for this comparison — a minor boundary assumption, not a
    # compliance/safety call, so not escalated to the open-questions register.
    visit_start = datetime.combine(visit.visit_date, time.min, tzinfo=UTC)
    hours_since_visit = (context.now - visit_start).total_seconds() / 3600
    if hours_since_visit > account.recency_window_hours:
        return _suppressed(SuppressionReason.stale_visit)

    if context.has_duplicate_encounter:
        return _suppressed(SuppressionReason.duplicate_encounter)

    if context.already_called_this_visit:
        return _suppressed(SuppressionReason.already_called_visit)

    if context.calls_in_frequency_window >= account.frequency_cap_count:
        return _suppressed(SuppressionReason.frequency_cap)

    if context.shared_number_count_in_batch > account.shared_number_threshold:
        return EligibilityDecision(
            status=EligibilityStatus.review, reason=SuppressionReason.shared_number_review
        )

    return EligibilityDecision(status=EligibilityStatus.eligible, reason=None)
