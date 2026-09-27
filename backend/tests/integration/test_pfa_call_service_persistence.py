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
from app.db.models.cases import Case, Complaint, PfaEscalation
from app.db.models.demo import Callback, DoNotCall
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
