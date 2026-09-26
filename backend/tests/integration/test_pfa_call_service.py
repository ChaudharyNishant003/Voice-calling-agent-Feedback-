"""`pfa_call_service.process_turn`/`start_turn` — the conversation graph's full per-turn
orchestration (PRD v2 §5, Phase 4 acceptance check: "mock-LLM integration tests pass").

No database is involved — `process_turn`/`start_turn` are pure functions of `(CallState, event,
persona, history, an LLM adapter)`, so these are plain async tests against a queued stub adapter,
mirroring `test_demo_playground_service.py`'s style (stateless, no `superadmin_session` fixture).
"""

from __future__ import annotations

import json

from app.adapters.interfaces import LLMAdapter, LLMResult
from app.adapters.registry import AdapterRegistry
from app.domain.conversation_graph.graph import Node
from app.domain.conversation_graph.scripts import ScriptForm
from app.domain.conversation_graph.state import (
    CallOutcome,
    CallState,
    ComplaintDraft,
    TopicCategory,
)
from app.services import pfa_call_service as svc

_PERSONA = svc.PersonaContext(
    hospital_name="Apollo Demo Hospital",
    agent_name="Priya",
    voice_gender="female",
    first_name="Ramesh",
    hospital_phone="9876543210",
    escalation_sla_text="chaubees ghante",
    tts_script=ScriptForm.roman,
    visit_date_words="das September",
)


class _QueueLLM:
    """Returns each queued contract dict in order, one per `.complete()` call — ignores the
    variables entirely (unlike `FakeLLM`'s exact-hash fixture matching, which would be brittle
    against this engine's large, ever-changing state-summary/history payload).
    """

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.calls.append((prompt_id, variables))
        if not self._responses:
            raise AssertionError("LLM queue exhausted — test scripted fewer turns than exercised")
        data = self._responses.pop(0)
        return LLMResult(
            data=data,
            raw_text=json.dumps(data),
            input_tokens=10,
            output_tokens=5,
            model="stub",
            latency_ms=1,
        )

    async def classify(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover - unused
        raise NotImplementedError

    async def extract(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover - unused
        raise NotImplementedError

    async def summarise(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover - unused
        raise NotImplementedError


def _registry(responses: list[dict[str, object]]) -> tuple[AdapterRegistry[LLMAdapter], _QueueLLM]:
    llm = _QueueLLM(responses)
    registry: AdapterRegistry[LLMAdapter] = AdapterRegistry()
    registry.register("stub", llm)
    return registry, llm


def _contract(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "reply_text": "Samajh gayi.",
        "language_detected": "hinglish",
        "register": "casual",
        "intents": [],
        "topics": [],
        "complaint_update": None,
        "rating": None,
        "severity_proposal": None,
        "safety": {"flag": False, "category": "none", "confidence": 0.0},
        "proposed_next": "open_and_identify",
        "clinical_question": None,
    }
    base.update(overrides)
    return base


async def _turn(
    state: CallState, registry: AdapterRegistry[LLMAdapter], text: str, kind: str = "utterance"
) -> svc.TurnResult:
    return await svc.process_turn(
        state=state,
        event_kind=kind,  # type: ignore[arg-type]
        event_text=text,
        persona=_PERSONA,
        history=[],
        registry=registry,
        provider="stub",
    )


def test_start_turn_speaks_fixed_opening_with_no_llm_call() -> None:
    result = svc.start_turn(_PERSONA)
    assert result.state.node == Node.open_and_identify
    assert not result.ended
    assert "Ramesh" in result.display_text
    assert "Apollo Demo Hospital" in result.display_text


async def test_confirms_identity_moves_to_consent_no_llm_reply_used() -> None:
    registry, llm = _registry([_contract(intents=["affirm"], proposed_next="purpose_consent_time")])
    state = CallState(node=Node.open_and_identify)
    result = await _turn(state, registry, "Haan, main Ramesh bol raha hoon")
    assert result.state.node == Node.purpose_consent_time
    assert not result.ended
    assert len(llm.calls) == 1
    # FIXED line replaces the LLM's own reply_text for this transition.
    assert "do-teen minute" in result.display_text or "two to three minutes" in result.display_text


async def test_full_happy_path_reaches_close_completed() -> None:
    responses = [
        _contract(intents=["affirm"], proposed_next="purpose_consent_time"),
        _contract(intents=["affirm"], proposed_next="open_experience"),
        _contract(
            reply_text="Bahut achha, samajh gayi.",
            topics=[
                {
                    "category": "doctor",
                    "sentiment": "positive",
                    "verbatim": "doctor bahut achhe the",
                    "staff_name": None,
                }
            ],
            proposed_next="overall_rating",
        ),
        _contract(rating={"value": 5, "inferred": False}, proposed_next="anything_else"),
        _contract(proposed_next="readback_and_next_steps"),
        _contract(reply_text="Sab kuch theek tha.", proposed_next="close"),
    ]
    registry, llm = _registry(responses)
    state = CallState(node=Node.open_and_identify)

    result = await _turn(state, registry, "Haan ji")
    result = await _turn(result.state, registry, "Haan theek hai")
    result = await _turn(result.state, registry, "Doctor bahut achhe the")
    result = await _turn(result.state, registry, "Paanch")
    result = await _turn(result.state, registry, "Nahi, bas itna hi")
    result = await _turn(result.state, registry, "Haan sahi hai")

    assert result.ended is True
    assert result.state.node == Node.close
    assert result.state.call_outcome == CallOutcome.completed
    assert result.state.rating == 5
    assert len(llm.calls) == 6


async def test_opt_out_ends_call_without_calling_llm() -> None:
    registry, llm = _registry([])
    state = CallState(node=Node.probe_topics)
    result = await _turn(state, registry, "Mujhe nahi chahiye, call mat karo")
    assert result.ended is True
    assert result.state.call_outcome == CallOutcome.opt_out
    assert result.state.do_not_call is True
    assert len(llm.calls) == 0


async def test_wants_human_ends_call_as_callback_without_llm() -> None:
    registry, llm = _registry([])
    state = CallState(node=Node.probe_topics)
    result = await _turn(state, registry, "Mujhe kisi insaan se baat karni hai")
    assert result.ended is True
    assert result.state.call_outcome == CallOutcome.callback
    assert result.state.wants_human is True
    assert len(llm.calls) == 0


async def test_safety_keyword_hit_escalates_without_calling_llm() -> None:
    registry, llm = _registry([])
    state = CallState(node=Node.open_experience, identity_verified=True)
    result = await _turn(state, registry, "Mujhe saans nahi aa rahi")
    assert result.state.node == Node.escalate_urgent
    assert len(result.state.escalations) == 1
    assert result.state.escalations[0].triggered_by == "keyword"
    assert len(llm.calls) == 0
    assert "ek ek do" in result.display_text or "emergency" in result.display_text.lower()


async def test_safety_llm_flag_escalates_even_without_keyword() -> None:
    responses = [
        _contract(
            proposed_next="probe_topics",
            safety={"flag": True, "category": "self_harm", "confidence": 0.9},
        )
    ]
    registry, llm = _registry(responses)
    state = CallState(node=Node.probe_topics, identity_verified=True)
    result = await _turn(state, registry, "kuch normal si baat")
    assert result.state.node == Node.escalate_urgent
    assert result.state.escalations[0].triggered_by == "llm"
    assert result.state.escalations[0].category == "self_harm"
    assert len(llm.calls) == 1


async def test_severity_s3_complaint_auto_advances_to_probe_topics() -> None:
    responses = [
        _contract(
            complaint_update={
                "category": "billing",
                "description": "Overcharged for a test",
                "when": "kal",
                "where": None,
                "wants_contact": True,
                "preferred_time": None,
            },
            severity_proposal="S3",
            proposed_next="severity_gate",
        )
    ]
    registry, llm = _registry(responses)
    # Seed one open complaint the way probe_topics would have.
    state = CallState(
        node=Node.complaint_detail,
        identity_verified=True,
        complaints=(ComplaintDraft(category=TopicCategory.billing, description="Overcharged"),),
        current_complaint_index=0,
    )

    result = await _turn(state, registry, "Bill mein galat amount tha")
    assert not result.ended
    assert result.state.node == Node.probe_topics
    assert result.state.current_complaint_index is None
    assert result.state.complaints[0].severity is not None
    assert len(llm.calls) == 1
    assert "team tak" in result.display_text or "team" in result.display_text.lower()


async def test_illegal_transition_proposal_is_rejected_and_logged() -> None:
    responses = [_contract(proposed_next="close")]  # not a legal edge from open_and_identify
    registry, llm = _registry(responses)
    state = CallState(node=Node.open_and_identify)
    result = await _turn(state, registry, "kuch bhi")
    assert result.state.node == Node.open_and_identify
    assert any(evt == "ILLEGAL_TRANSITION_PROPOSED" for evt, _ in result.events)
    assert len(llm.calls) == 1


async def test_silence_first_then_second_ends_call_without_llm() -> None:
    registry, llm = _registry([])
    state = CallState(node=Node.probe_topics)
    first = await _turn(state, registry, "", kind="silence")
    assert not first.ended
    assert first.state.consecutive_silences == 1

    second = await _turn(first.state, registry, "", kind="silence")
    assert second.ended is True
    assert second.state.call_outcome == CallOutcome.callback
    assert len(llm.calls) == 0


async def test_llm_contract_failure_twice_falls_back_to_fixed_repair_line() -> None:
    registry: AdapterRegistry[LLMAdapter] = AdapterRegistry()

    class _AlwaysMalformed:
        calls = 0

        async def complete(
            self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
        ) -> LLMResult:
            self.calls += 1
            return LLMResult(
                data={},
                raw_text="{not valid",
                input_tokens=1,
                output_tokens=1,
                model="x",
                latency_ms=1,
            )

        async def classify(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover
            raise NotImplementedError

        async def extract(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover
            raise NotImplementedError

        async def summarise(self, *a: object, **k: object) -> LLMResult:  # pragma: no cover
            raise NotImplementedError

    broken = _AlwaysMalformed()
    registry.register("stub", broken)
    state = CallState(node=Node.open_and_identify)
    result = await _turn(state, registry, "kuch bolo")
    assert broken.calls == 2
    assert any(evt == "LLM_CONTRACT_ERROR" for evt, _ in result.events)
    assert result.state.node == Node.open_and_identify  # fallback proposes staying put


async def test_guard_truncates_an_overly_long_llm_reply() -> None:
    long_reply = " ".join(["word"] * 40)
    responses = [_contract(reply_text=long_reply, proposed_next="probe_topics")]
    registry, llm = _registry(responses)
    state = CallState(node=Node.open_experience, identity_verified=True)
    result = await _turn(state, registry, "Bahut kuch bataya")
    assert len(result.display_text.split()) <= 30
    assert any(evt == "GUARD_EVENT" for evt, _ in result.events)
