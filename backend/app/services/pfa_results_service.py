"""Read-side reporting for the conversation graph (PRD v2 §11-12): the results list/detail and the
escalations queue. Deliberately separate from `pfa_call_service.py` (which is the write-side
conversation orchestrator) — this module only reads.

Most of a call's structured output (topics, complaints incl. severity, rating, outcome) is read
straight from `Call.state_snapshot` — it's already the single source of truth for a finished call's
engine state (see `pfa_call_service._deserialize_state`), so re-normalizing it into fresh queryable
columns here would just be a second, driftable copy. `PfaEscalation` rows are read from their own
table instead, since acknowledgement status has its own post-call lifecycle (§11's
`POST /demo/escalations/{id}/ack`) that `state_snapshot` was already frozen before.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError as PFANotFoundError
from app.core.security import decrypt, get_local_kek
from app.db.models.calls import Call
from app.db.models.cases import PfaEscalation
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Department
from app.db.repositories.encryption_keys import get_or_create_dek
from app.services.pfa_call_service import deserialize_state, load_history


class EscalationNotFoundError(PFANotFoundError):
    pass


@dataclass(frozen=True)
class ResultListItem:
    call_id: UUID
    started_at: datetime | None
    ended_at: datetime | None
    patient_first_name: str | None
    visit_type: str
    department: str | None
    outcome: str | None
    rating: int | None
    severity_max: str | None
    complaint_count: int
    escalated: bool


@dataclass(frozen=True)
class ResultDetail:
    call_id: UUID
    patient_first_name: str | None
    visit_type: str
    visit_date: str
    department: str | None
    doctor_name: str | None
    outcome: str | None
    respondent_type: str
    language_mode: str | None
    rating: int | None
    rating_inferred: bool
    topics: list[dict[str, object]]
    complaints: list[dict[str, object]]
    escalations: list[dict[str, object]]
    transcript: list[tuple[str, str]]


_SEVERITY_ORDER = ["S0", "S1", "S2", "S3", "S4"]


def _severity_max(complaint_severities: list[str | None]) -> str | None:
    present = [s for s in complaint_severities if s is not None]
    if not present:
        return None
    return max(present, key=_SEVERITY_ORDER.index)


async def _decrypt_first_name(session: AsyncSession, patient: Patient | None) -> str | None:
    if patient is None or patient.first_name_enc is None:
        return None
    kek = get_local_kek()
    dek = await get_or_create_dek(session, patient.account_id, kek=kek)
    return decrypt(patient.first_name_enc, dek)


async def list_results(session: AsyncSession, *, limit: int = 100) -> list[ResultListItem]:
    calls = list(
        (
            await session.scalars(
                select(Call).order_by(Call.scheduled_at.desc()).limit(limit)
            )
        ).all()
    )
    out: list[ResultListItem] = []
    for call in calls:
        visit = await session.get(Visit, call.visit_id)
        if visit is None:
            continue
        patient = await session.get(Patient, visit.patient_ref_id)
        department = await session.get(Department, visit.department_id)
        state_data = call.state_snapshot or {}
        complaints = state_data.get("complaints", [])
        severities = [c.get("severity") for c in complaints] if isinstance(complaints, list) else []
        out.append(
            ResultListItem(
                call_id=call.call_id,
                started_at=call.started_at,
                ended_at=call.ended_at,
                patient_first_name=await _decrypt_first_name(session, patient),
                visit_type=visit.visit_type.value,
                department=department.name if department else None,
                outcome=state_data.get("call_outcome"),  # type: ignore[arg-type]
                rating=state_data.get("rating"),  # type: ignore[arg-type]
                severity_max=_severity_max(severities),
                complaint_count=len(complaints) if isinstance(complaints, list) else 0,
                escalated=bool(state_data.get("escalations")),
            )
        )
    return out


async def get_result_detail(session: AsyncSession, call_id: UUID) -> ResultDetail:
    call = await session.get(Call, call_id)
    if call is None:
        raise PFANotFoundError("PFA-DEMO-006", message="Demo call not found.")
    visit = await session.get(Visit, call.visit_id)
    assert visit is not None
    patient = await session.get(Patient, visit.patient_ref_id)
    department = await session.get(Department, visit.department_id)

    state = deserialize_state(call.state_snapshot or {})
    history = await load_history(session, call)

    return ResultDetail(
        call_id=call.call_id,
        patient_first_name=await _decrypt_first_name(session, patient),
        visit_type=visit.visit_type.value,
        visit_date=visit.visit_date.isoformat(),
        department=department.name if department else None,
        doctor_name=visit.doctor_name,
        outcome=state.call_outcome.value if state.call_outcome else None,
        respondent_type=state.respondent_type.value,
        language_mode=state.language.locked.value if state.language.locked else None,
        rating=state.rating,
        rating_inferred=state.rating_inferred,
        topics=[
            {
                "category": t.category.value,
                "sentiment": t.sentiment.value,
                "verbatim": t.verbatim,
                "staff_name": t.staff_name,
            }
            for t in state.topics
        ],
        complaints=[
            {
                "category": c.category.value,
                "description": c.description,
                "severity": c.severity.value if c.severity else None,
                "when_text": c.when_text,
                "where_text": c.where_text,
                "wants_contact": c.wants_contact,
                "staff_name": c.staff_name,
            }
            for c in state.complaints
        ],
        escalations=[
            {
                "severity": e.severity.value,
                "category": str(e.category),
                "triggered_by": e.triggered_by,
            }
            for e in state.escalations
        ],
        transcript=history,
    )


async def list_escalations(
    session: AsyncSession, *, status: str | None = None
) -> list[PfaEscalation]:
    query = select(PfaEscalation).order_by(PfaEscalation.created_at.desc())
    if status is not None:
        query = query.where(PfaEscalation.status == status)
    return list((await session.scalars(query)).all())


async def acknowledge_escalation(session: AsyncSession, escalation_id: UUID) -> PfaEscalation:
    escalation = await session.get(PfaEscalation, escalation_id)
    if escalation is None:
        raise EscalationNotFoundError("PFA-DEMO-011", message="Escalation not found.")
    escalation.status = "acknowledged"
    escalation.acknowledged_at = datetime.now(UTC)
    await session.flush()
    return escalation
