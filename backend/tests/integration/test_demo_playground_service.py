"""`demo_playground_service`'s seven pipeline-stage functions (docs/11_BUILD_PLAN.md's Demo MVP
section) — the four LLM-backed stages against a stub adapter (happy path + malformed-output
mapping to the catalogued error, never a crash), and the three deterministic stages' correct
delegation to the existing domain functions (their exhaustive rule coverage already lives in
test_conversation_language.py/test_conversation_topics.py — this just confirms the wiring).

No database is involved: the Playground is stateless by design, so these are plain async tests, not
`superadmin_session`-backed integration tests — kept in `tests/integration/` anyway to sit next to
`test_demo_conversation_service.py`, which it deliberately mirrors the style of.
"""

from __future__ import annotations

import json

from app.adapters.interfaces import LLMResult
from app.core.errors import AdapterBadResponse
from app.services import demo_playground_service as svc


class _StubLLM:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.calls.append((prompt_id, variables))
        return LLMResult(
            data=self._data,
            raw_text=json.dumps(self._data),
            input_tokens=7,
            output_tokens=3,
            model="stub-model",
            latency_ms=42,
        )


async def test_language_detection_happy_path() -> None:
    llm = _StubLLM({"detected_language": "hi", "requested_language": None})
    outcome = await svc.run_language_detection(llm, patient_text="Sab theek tha")
    assert outcome.parsed.detected_language == "hi"
    assert outcome.parsed.requested_language is None
    assert outcome.latency_ms == 42
    assert outcome.input_tokens == 7
    assert outcome.output_tokens == 3
    assert outcome.model == "stub-model"
    assert llm.calls[0][0] == "playground_language_detection"


async def test_language_detection_malformed_output_raises_catalogued_error() -> None:
    llm = _StubLLM({"detected_language": "not-a-real-language"})
    try:
        await svc.run_language_detection(llm, patient_text="hello")
        raise AssertionError("expected AdapterBadResponse")
    except AdapterBadResponse as exc:
        assert exc.code == "PFA-DEMO-004"


async def test_topic_extraction_happy_path() -> None:
    llm = _StubLLM({"topics": ["waiting_time", "billing"]})
    outcome = await svc.run_topic_extraction(
        llm, patient_text="Waiting bahut zyada thi aur billing confusing"
    )
    assert outcome.parsed.topics == ["waiting_time", "billing"]
    assert llm.calls[0][0] == "playground_topic_extraction"


async def test_end_judgment_happy_path() -> None:
    llm = _StubLLM({"wants_to_end": True, "summary": "Feedback collected."})
    outcome = await svc.run_end_judgment(
        llm,
        patient_text="Bas itna hi tha",
        topics_covered=frozenset({"doctor", "staff"}),
        turn_count=4,
    )
    assert outcome.parsed.wants_to_end is True
    assert outcome.parsed.summary == "Feedback collected."
    assert llm.calls[0][0] == "playground_end_judgment"


async def test_response_generation_happy_path() -> None:
    llm = _StubLLM({"response": "Dhanyavaad!", "next_action": "close"})
    outcome = await svc.run_response_generation(
        llm,
        hospital_name="Apollo Test Hospital",
        agent_name="Riya",
        voice_gender="female",
        locked_language="hindi_hinglish",
        topics_covered=frozenset({"doctor"}),
        is_ending=True,
        patient_text="Sab badhiya tha",
    )
    assert outcome.parsed.response == "Dhanyavaad!"
    assert outcome.parsed.next_action == "close"
    assert llm.calls[0][0] == "playground_response_generation"


def test_language_lock_first_turn_locks_without_switching() -> None:
    outcome = svc.run_language_lock(
        detected_language="hi",
        requested_language=None,
        prior_locked_language=None,
        prior_streak=0,
    )
    assert outcome.locked_language == "hindi_hinglish"
    assert outcome.switched is False


def test_language_lock_explicit_request_switches_immediately() -> None:
    outcome = svc.run_language_lock(
        detected_language="en",
        requested_language="hi",
        prior_locked_language="english",
        prior_streak=0,
    )
    assert outcome.locked_language == "hindi_hinglish"
    assert outcome.switched is True


def test_topic_tracking_merges_new_and_prior() -> None:
    outcome = svc.run_topic_tracking(
        topics_mentioned=["billing"], prior_topics_covered=["doctor", "staff"]
    )
    assert outcome.topics_covered == ["billing", "doctor", "staff"]


def test_end_ceiling_forces_end_at_max_turns_regardless_of_model_signal() -> None:
    assert svc.run_end_ceiling(turn_count=8, llm_wants_to_end=False) is True


def test_end_ceiling_does_not_end_below_min_turns_even_if_model_wants_to() -> None:
    assert svc.run_end_ceiling(turn_count=1, llm_wants_to_end=True) is False
