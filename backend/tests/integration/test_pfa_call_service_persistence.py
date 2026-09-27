"""Real Postgres: `pfa_call_service`'s persistence layer (PRD v2 Phase 5) — start_call/submit_turn/
end_call actually writing Patient/Visit/Call/Transcript/CallEvent rows, resuming state from
`Call.state_snapshot` across turns, and turning a finished call's `CallState` into
Complaint/Case/CaseEvent/PfaEscalation/DoNotCall/Callback records.

Uses a sequence-based stub `LLMAdapter` (same shape as `test_demo_conversation_service.py`'s
`_SequenceLLM`) rather than `FakeLLM`'s exact-hash fixture matching, which doesn't fit this
engine's large, ever-changing per-turn prompt payload.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.interfaces import LLMResult
from app.adapters.registry import AdapterRegistry
from app.core.config import get_settings
from app.core.ids import uuid7
from app.core.phone import phone_hash
from app.core.security import encrypt, get_local_kek
from app.db.models.cases import Case, Complaint, PfaEscalation
from app.db.models.demo import Callback, DoNotCall
from app.db.models.enums import VisitType
from app.db.models.patients_visits import Patient, Visit
from app.db.repositories.encryption_keys import get_or_create_dek
from app.services import demo_conversation_service
from app.services import pfa_call_service as svc


class _SequenceLLM:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.call_count += 1
        item = self._responses.pop(0)
        return LLMResult(
            data=item, raw_text=json.dumps(item), input_tokens=1, output_tokens=1,
            model="fake", latency_ms=1,
        )

    async def classify(self, *a: object, **kw: object) -> LLMResult:
        return await self.complete(*a, **kw)  # type: ignore[arg-type]

    async def extract(self, *a: object, **kw: object) -> LLMResult:
        return await self.complete(*a, **kw)  # type: ignore[arg-type]

    async def summarise(self, *a: object, **kw: object) -> LLMResult:
        return await self.complete(*a, **kw)  # type: ignore[arg-type]


def _registry(llm: _SequenceLLM) -> AdapterRegistry:  # type: ignore[type-arg]
    registry = AdapterRegistry()  # type: ignore[var-annotated]
    registry.register("gemini", llm)
    return registry


def _contract(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "reply_text": "Samajh gayi.",
        "language_detected": "hinglish",
        "proposed_next": "open_and_identify",
    }
    base.update(overrides)
    return base


def _start_input(**overrides: object) -> svc.StartCallInput:
    base: dict[str, object] = {
        "provider": "gemini",
        "patient_first_name": "Ramesh",
        "patient_phone": "+919812345678",
        "visit_type": "OPD",
        "visit_date": date(2026, 9, 20),
        "department": "Cardiology",
        "doctor_name": "Dr. Rao",
        "patient_age": 45,
    }
    base.update(overrides)
    return svc.StartCallInput(**base)  # type: ignore[arg-type]


async def test_start_call_persists_patient_visit_call_and_greeting(
    superadmin_session: AsyncSession,
) -> None:
    result = await svc.start_call(superadmin_session, _start_input())
    assert result.node == "open_and_identify"
    assert not result.ended
    assert "Ramesh" in result.display_text


async def test_full_happy_path_persists_case_and_escalation_on_severe_complaint(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, _start_input())
    llm = _SequenceLLM(
        [
            _contract(intents=["affirm"], proposed_next="purpose_consent_time"),
            _contract(intents=["affirm"], proposed_next="open_experience"),
            _contract(
                topics=[
                    {
                        "category": "billing",
                        "sentiment": "negative",
                        "verbatim": "overcharged for a test",
                        "staff_name": None,
                    }
                ],
                proposed_next="probe_topics",
            ),
            _contract(
                complaint_update={
                    "category": "billing",
                    "description": "Overcharged for a routine test",
                    "when": "kal",
                    "where": None,
                    "wants_contact": True,
                    "preferred_time": None,
                },
                proposed_next="complaint_detail",
            ),
            _contract(
                complaint_update={
                    "category": "billing",
                    "description": "Overcharged by two thousand rupees",
                    "when": None,
                    "where": None,
                    "wants_contact": None,
                    "preferred_time": None,
                },
                severity_proposal="S3",
                proposed_next="severity_gate",
            ),
            _contract(proposed_next="overall_rating"),
            _contract(rating={"value": 4, "inferred": False}, proposed_next="anything_else"),
            _contract(proposed_next="readback_and_next_steps"),
            _contract(reply_text="Billing overcharge complaint.", proposed_next="close"),
        ]
    )
    registry = _registry(llm)

    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Haan ji"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Haan theek hai"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance",
        "Billing mein overcharge hua tha",
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Kal hua tha"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance",
        "Do hazaar rupaye zyada le liye",
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Nahi bas itna hi"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Chaar dunga"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Nahi kuch nahi"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Haan sahi hai"
    )

    assert r.ended is True
    assert r.call_outcome == "completed"

    complaint = await superadmin_session.scalar(
        select(Complaint).where(Complaint.call_id == started.call_id)
    )
    assert complaint is not None
    assert complaint.when_text == "kal"
    assert complaint.wants_contact is True

    case = await superadmin_session.scalar(
        select(Case).where(Case.complaint_id == complaint.complaint_id)
    )
    assert case is not None
    assert case.priority.value == "p2"  # S3 -> p2

    escalation = await superadmin_session.scalar(
        select(PfaEscalation).where(PfaEscalation.call_id == started.call_id)
    )
    assert escalation is not None
    assert escalation.type == "standard"
    # Escalations persist as soon as they're triggered (per turn), before the complaint/case they
    # relate to is finalized at call-end — see `_persist_new_escalations`'s docstring.
    assert escalation.complaint_id is None
    assert escalation.case_id is None


async def test_opt_out_persists_do_not_call_and_blocks_next_call(
    superadmin_session: AsyncSession,
) -> None:
    phone = "+919812399999"
    started = await svc.start_call(superadmin_session, _start_input(patient_phone=phone))
    registry = _registry(_SequenceLLM([]))

    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance",
        "Mujhe nahi chahiye, call mat karo",
    )
    assert r.ended is True
    assert r.call_outcome == "opt_out"

    dnc = await superadmin_session.scalar(
        select(DoNotCall).where(DoNotCall.source_call_id == started.call_id)
    )
    assert dnc is not None

    try:
        await svc.start_call(superadmin_session, _start_input(patient_phone=phone))
        raise AssertionError("expected PatientOnDoNotCallError")
    except svc.PatientOnDoNotCallError as exc:
        assert exc.code == "PFA-DEMO-010"


async def test_safety_keyword_escalation_persists_urgent_case_without_llm_call(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, _start_input())
    registry = _registry(_SequenceLLM([_contract(proposed_next="purpose_consent_time")]))

    await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Haan ji"
    )
    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance",
        "Mujhe saans nahi aa rahi",
    )
    assert r.node == "escalate_urgent"
    assert r.escalated is True

    escalation = await superadmin_session.scalar(
        select(PfaEscalation).where(PfaEscalation.call_id == started.call_id)
    )
    assert escalation is not None
    assert escalation.type == "urgent"
    assert escalation.triggered_by == "keyword"
    assert escalation.category == "medical_now"


async def test_callback_on_wants_human_persists_callback_record(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, _start_input())
    registry = _registry(_SequenceLLM([]))

    r = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance",
        "Mujhe kisi insaan se baat karni hai",
    )
    assert r.ended is True
    assert r.call_outcome == "callback"

    callback = await superadmin_session.scalar(
        select(Callback).where(Callback.call_id == started.call_id)
    )
    assert callback is not None
    assert callback.reason == "wants_human"


async def test_state_resumes_correctly_across_turns_from_state_snapshot(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, _start_input())
    registry = _registry(
        _SequenceLLM(
            [
                _contract(intents=["affirm"], proposed_next="purpose_consent_time"),
                _contract(intents=["affirm"], proposed_next="open_experience"),
            ]
        )
    )
    r1 = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Haan ji"
    )
    assert r1.node == "purpose_consent_time"
    r2 = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "Theek hai"
    )
    assert r2.node == "open_experience"


async def test_patient_first_name_still_present_when_open_and_identify_self_loops(
    superadmin_session: AsyncSession,
) -> None:
    """Regression test: confirmed live against the real Gemini API — an illegal `proposed_next`
    self-loops the state back onto `open_and_identify`, whose FIXED script needs {first_name} on
    *any* turn it renders, not only the very first one.
    """
    started = await svc.start_call(superadmin_session, _start_input(patient_first_name="Sunita"))
    llm = _SequenceLLM([_contract(proposed_next="not_a_real_node")])
    registry = _registry(llm)

    result = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "utterance", "kuch bhi"
    )
    assert result.node == "open_and_identify"
    assert "Sunita" in result.display_text
    assert llm.call_count == 1


async def _ingested_visit(superadmin_session: AsyncSession) -> Visit:
    """Simulates a row that came from the existing S1.6 CSV ingestion (a Patient/Visit pair with
    no first_name_enc — REQUIRED_COLUMNS in domain/ingestion_csv.py has no name field at all) —
    without driving the actual Celery-backed upload pipeline, which this test doesn't need to
    exercise; it only needs a real, pre-existing visit for start_call_from_visit to read.
    """
    account = await demo_conversation_service.get_or_create_demo_account(superadmin_session)
    location = await demo_conversation_service.get_or_create_demo_location(
        superadmin_session, account.account_id
    )
    department = await demo_conversation_service.get_or_create_demo_department(
        superadmin_session, account.account_id
    )
    kek = get_local_kek()
    dek = await get_or_create_dek(superadmin_session, account.account_id, kek=kek)
    pepper = get_settings().phone_hash_pepper
    phone = "+919800011122"
    patient = Patient(
        patient_ref_id=uuid7(),
        account_id=account.account_id,
        external_patient_id=f"csv-{uuid7().hex}",
        phone_hash=bytes.fromhex(phone_hash(phone, pepper=pepper)),
        phone_e164_enc=encrypt(phone, dek),
        phone_last4=phone[-4:],
    )
    superadmin_session.add(patient)
    await superadmin_session.flush()

    visit = Visit(
        visit_id=uuid7(),
        account_id=account.account_id,
        location_id=location.location_id,
        patient_ref_id=patient.patient_ref_id,
        department_id=department.department_id,
        external_visit_key=f"csv-{uuid7().hex}",
        visit_date=date(2026, 9, 20),
        visit_type=VisitType.outpatient,
        patient_age=40,
    )
    superadmin_session.add(visit)
    await superadmin_session.flush()
    return visit


async def test_start_call_from_visit_uses_operator_supplied_name(
    superadmin_session: AsyncSession,
) -> None:
    visit = await _ingested_visit(superadmin_session)
    result = await svc.start_call_from_visit(
        superadmin_session, visit_id=visit.visit_id, provider="gemini", patient_first_name="Anita"
    )
    assert "Anita" in result.display_text
    assert result.node == "open_and_identify"


async def test_start_call_from_visit_reuses_saved_name_on_a_second_call(
    superadmin_session: AsyncSession,
) -> None:
    visit = await _ingested_visit(superadmin_session)
    first = await svc.start_call_from_visit(
        superadmin_session, visit_id=visit.visit_id, provider="gemini", patient_first_name="Anita"
    )
    # A visit can only have one active call at a time — end it before the next attempt, same as a
    # real retry would.
    await svc.end_call(superadmin_session, first.call_id)
    # A second call for the same patient (e.g. a retry) doesn't need the name repeated.
    result = await svc.start_call_from_visit(
        superadmin_session, visit_id=visit.visit_id, provider="gemini", patient_first_name=None
    )
    assert "Anita" in result.display_text


async def test_start_call_from_visit_404s_for_an_unknown_visit(
    superadmin_session: AsyncSession,
) -> None:
    from uuid import uuid4

    try:
        await svc.start_call_from_visit(
            superadmin_session, visit_id=uuid4(), provider="gemini", patient_first_name="X"
        )
        raise AssertionError("expected VisitNotFoundError")
    except svc.VisitNotFoundError as exc:
        assert exc.code == "PFA-DEMO-012"
