"""Eligibility I/O layer (docs/03_CALL_FLOW_AND_CONVERSATION.md §1) — gathers everything
`domain.eligibility.evaluate` needs, then persists its decision. The pure rule logic itself lives in
`app.domain.eligibility`; this module only does queries and writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.calls import Call
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account
from app.domain.eligibility import (
    EligibilityAccountConfig,
    EligibilityContext,
    EligibilityDecision,
    EligibilityPatient,
    EligibilityVisit,
    evaluate,
)
from app.domain.enums import EligibilityStatus
from app.services import audit_service

# Call statuses that count as "this visit has already been contacted" (rule 9).
_TERMINAL_CONTACTED_STATUSES = ("completed", "consent_declined")

# suppression_list.reason values that map to rule 5 ("opt-out") rather than rule 6 ("dnd") — every
# reason except 'dnd' is treated as opt-out-equivalent (errs toward suppression, since under-
# blocking is the compliance-risky direction; see docs/12_OPEN_QUESTIONS.md discussion pattern).
_OPT_OUT_REASONS = ("opt_out", "consent_declined", "manual", "deleted")


class VisitNotFoundError(ValueError):
    pass


async def _is_opted_out(session: AsyncSession, account_id: UUID, phone_hash: bytes) -> bool:
    from app.db.models.compliance import SuppressionEntry

    stmt = select(
        exists().where(
            SuppressionEntry.phone_hash == phone_hash,
            SuppressionEntry.reason.in_(_OPT_OUT_REASONS),
            (SuppressionEntry.account_id == account_id) | (SuppressionEntry.account_id.is_(None)),
        )
    )
    return bool(await session.scalar(stmt))


async def _is_dnd(session: AsyncSession, account_id: UUID, phone_hash: bytes) -> bool:
    from app.db.models.compliance import SuppressionEntry

    stmt = select(
        exists().where(
            SuppressionEntry.phone_hash == phone_hash,
            SuppressionEntry.reason == "dnd",
            (SuppressionEntry.account_id == account_id) | (SuppressionEntry.account_id.is_(None)),
            SuppressionEntry.campaign_type.is_(None)
            | (SuppressionEntry.campaign_type == "service_feedback"),
        )
    )
    return bool(await session.scalar(stmt))


async def _has_duplicate_encounter(
    session: AsyncSession, visit: Visit, dedupe_window_days: int
) -> bool:
    window_start = visit.visit_date - timedelta(days=dedupe_window_days)
    window_end = visit.visit_date + timedelta(days=dedupe_window_days)
    stmt = select(
        exists().where(
            Visit.patient_ref_id == visit.patient_ref_id,
            Visit.visit_id != visit.visit_id,
            Visit.visit_date.between(window_start, window_end),
            (
                (Visit.eligibility_status == EligibilityStatus.eligible)
                | exists().where(Call.visit_id == Visit.visit_id)
            ),
        )
    )
    return bool(await session.scalar(stmt))


async def _already_called_this_visit(session: AsyncSession, visit_id: UUID) -> bool:
    stmt = select(
        exists().where(Call.visit_id == visit_id, Call.status.in_(_TERMINAL_CONTACTED_STATUSES))
    )
    return bool(await session.scalar(stmt))


async def _calls_in_frequency_window(
    session: AsyncSession, patient_ref_id: UUID, now: datetime, frequency_cap_days: int
) -> int:
    window_start = now - timedelta(days=frequency_cap_days)
    stmt = (
        select(func.count())
        .select_from(Call)
        .join(Visit, Visit.visit_id == Call.visit_id)
        .where(Visit.patient_ref_id == patient_ref_id, Call.scheduled_at >= window_start)
    )
    return int(await session.scalar(stmt) or 0)


async def _shared_number_count_in_batch(
    session: AsyncSession, visit: Visit, phone_hash: bytes
) -> int:
    if visit.batch_id is None:
        return 0
    stmt = (
        select(func.count(func.distinct(Patient.patient_ref_id)))
        .select_from(Visit)
        .join(Patient, Patient.patient_ref_id == Visit.patient_ref_id)
        .where(Visit.batch_id == visit.batch_id, Patient.phone_hash == phone_hash)
    )
    return int(await session.scalar(stmt) or 0)


async def evaluate_and_persist(
    session: AsyncSession, visit_id: UUID, *, now: datetime | None = None
) -> EligibilityDecision:
    now = now or datetime.now(UTC)

    visit = await session.get(Visit, visit_id)
    if visit is None:
        raise VisitNotFoundError(f"visit {visit_id} not found")
    patient = await session.get(Patient, visit.patient_ref_id)
    assert patient is not None  # FK guarantees this
    account = await session.get(Account, visit.account_id)
    assert account is not None  # FK guarantees this

    context = EligibilityContext(
        now=now,
        # Ingestion validates phone format before a Patient row ever exists (PFA-ING-011), so an
        # existing patient's phone is already known-valid — re-validating here would mean
        # decrypting the phone just to re-run a check ingestion already guarantees passed.
        is_valid_phone=True,
        is_opted_out=await _is_opted_out(session, visit.account_id, patient.phone_hash),
        is_dnd=await _is_dnd(session, visit.account_id, patient.phone_hash),
        has_duplicate_encounter=await _has_duplicate_encounter(
            session, visit, account.dedupe_window_days
        ),
        already_called_this_visit=await _already_called_this_visit(session, visit_id),
        calls_in_frequency_window=await _calls_in_frequency_window(
            session, visit.patient_ref_id, now, account.frequency_cap_days
        ),
        shared_number_count_in_batch=await _shared_number_count_in_batch(
            session, visit, patient.phone_hash
        ),
    )

    decision = evaluate(
        visit=EligibilityVisit(
            visit_type=visit.visit_type, visit_date=visit.visit_date, patient_age=visit.patient_age
        ),
        patient=EligibilityPatient(is_deleted=patient.deleted_at is not None),
        account=EligibilityAccountConfig(
            recency_window_hours=account.recency_window_hours,
            dedupe_window_days=account.dedupe_window_days,
            frequency_cap_days=account.frequency_cap_days,
            frequency_cap_count=account.frequency_cap_count,
            shared_number_threshold=account.shared_number_threshold,
        ),
        context=context,
    )

    visit.eligibility_status = decision.status
    visit.suppression_reason = decision.reason
    visit.eligibility_evaluated_at = now
    await session.flush()
    return decision


async def resolve_review(
    session: AsyncSession,
    visit_id: UUID,
    decision: Literal["eligible", "suppressed"],
    note: str,
    actor_id: UUID,
) -> Visit:
    """Human resolution of a `shared_number_review` visit (docs/07_SECURITY_AND_COMPLIANCE.md §6 —
    'eligibility review decisions' is a must-audit action).
    """
    visit = await session.get(Visit, visit_id)
    if visit is None:
        raise VisitNotFoundError(f"visit {visit_id} not found")

    before = {
        "eligibility_status": visit.eligibility_status.value,
        "suppression_reason": (
            visit.suppression_reason.value if visit.suppression_reason else None
        ),
    }

    visit.eligibility_status = (
        EligibilityStatus.eligible if decision == "eligible" else EligibilityStatus.suppressed
    )
    visit.suppression_reason = None if decision == "eligible" else visit.suppression_reason
    await session.flush()

    after = {
        "eligibility_status": visit.eligibility_status.value,
        "suppression_reason": (
            visit.suppression_reason.value if visit.suppression_reason else None
        ),
    }

    await audit_service.record(
        session,
        account_id=visit.account_id,
        actor_type="user",
        actor_id=actor_id,
        action="visit.eligibility_review",
        entity_type="visit",
        entity_id=visit_id,
        before=before,
        after={**after, "note": note},
    )
    return visit
