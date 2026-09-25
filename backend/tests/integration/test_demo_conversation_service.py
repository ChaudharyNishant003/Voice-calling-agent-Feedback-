"""Real Postgres: `demo_conversation_service`'s full call lifecycle (Demo MVP spec §11, §21-22) —
start_call -> several submit_turn calls, language lock/switch, topic tracking, the deterministic
end-of-call ceiling, and LLM-failure recovery (retry then fallback, session survives).

Uses a small sequence-based fake `LLMAdapter`, not the shared `app.adapters.fakes.FakeLLM`: that
fixture matches canned responses by an exact hash of `variables`, which here includes the full
system prompt + conversation history and so differs on every turn. A stub that returns
pre-programmed responses in call order fits this test shape better.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.interfaces import LLMResult
from app.adapters.registry import AdapterRegistry
from app.core.errors import AdapterBadResponse
from app.services import demo_conversation_service as svc


class _SequenceLLM:
    """Returns pre-programmed `DemoTurnResponse`-shaped dicts (or raises a given exception) in call
    order — one list entry consumed per `complete()` call.
    """

    def __init__(self, responses: list[dict[str, object] | Exception]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.call_count += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(
            data=item,
            raw_text=json.dumps(item),
            input_tokens=1,
            output_tokens=1,
            model="fake",
            latency_ms=1,
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


async def test_start_call_creates_call_and_greeting(superadmin_session: AsyncSession) -> None:
    result = await svc.start_call(superadmin_session, provider="gemini")
    assert result.greeting_text
    assert result.hospital_name
    assert result.agent_name

    timeline = await svc.get_timeline(superadmin_session, result.call_id)
    assert [e.type for e in timeline] == ["CALL_STARTED", "AGENT_GREETING"]


async def test_happy_path_locks_language_tracks_topics_and_ends(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, provider="gemini")
    llm = _SequenceLLM(
        [
            {
                "response": "Waiting ke baare mein bura laga, samajh sakti hoon.",
                "detected_language": "hi",
                "topics": ["waiting_time"],
                "next_action": "follow_up",
                "end_call": False,
            },
            {
                "response": "Staff ke baare mein bhi bataiye.",
                "detected_language": "en",  # single off-family turn — must NOT switch
                "topics": ["staff"],
                "next_action": "follow_up",
                "end_call": False,
            },
            {
                "response": "Dhanyavaad, feedback ke liye shukriya!",
                "detected_language": "hi",  # back to locked family — streak resets
                "topics": ["overall_experience"],
                "next_action": "summarize",
                "end_call": True,
                "summary": "Long waiting time; staff and overall experience otherwise fine.",
            },
        ]
    )
    registry = _registry(llm)

    r1 = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Waiting bahut zyada thi."
    )
    assert r1.locked_language == "hindi_hinglish"
    assert r1.switched_language is False
    assert r1.end_call is False

    r2 = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Staff was okay I guess."
    )
    assert r2.locked_language == "hindi_hinglish"  # one English turn doesn't switch the family
    assert r2.switched_language is False
    assert r2.end_call is False

    r3 = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Overall theek hi tha."
    )
    assert r3.locked_language == "hindi_hinglish"
    assert r3.end_call is True  # llm_wants_to_end AND turn_count(3) >= MIN_TURNS_BEFORE_END(3)
    assert r3.summary == "Long waiting time; staff and overall experience otherwise fine."
    assert set(r3.topics) == {"waiting_time", "staff", "overall_experience"}

    timeline = await svc.get_timeline(superadmin_session, started.call_id)
    assert timeline[-1].type == "CALL_ENDED"
    assert llm.call_count == 3


async def test_three_consecutive_off_family_turns_switch_language(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, provider="gemini")

    def _turn(lang: str, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "response": "ok",
            "detected_language": lang,
            "topics": [],
            "next_action": "follow_up",
            "end_call": False,
        }
        base.update(overrides)
        return base

    llm = _SequenceLLM(
        [
            _turn("hi"),  # turn 1: locks hindi_hinglish
            _turn("en"),  # turn 2: streak=1, still locked
            _turn("en"),  # turn 3: streak=2, still locked
            _turn("en"),  # turn 4: streak=3 -> switches to english
            # explicit override
            _turn("en", requested_language="hi", end_call=True, summary="done"),
        ]
    )
    registry = _registry(llm)

    results = []
    for text in ["Sab theek hai", "It was fine", "Staff was nice", "Doctor was good"]:
        results.append(
            await svc.submit_turn(superadmin_session, registry, started.call_id, "gemini", text)
        )
    assert [r.locked_language for r in results] == [
        "hindi_hinglish",
        "hindi_hinglish",
        "hindi_hinglish",
        "english",
    ]
    assert results[-1].switched_language is True

    final = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Hindi mein baat karo please"
    )
    # Explicit request overrides immediately, regardless of the (just-reset) streak.
    assert final.locked_language == "hindi_hinglish"
    assert final.switched_language is True
    assert final.end_call is True  # turn_count(5) >= MIN_TURNS_BEFORE_END(3) and llm_wants_to_end


async def test_llm_failure_retries_then_succeeds(superadmin_session: AsyncSession) -> None:
    started = await svc.start_call(superadmin_session, provider="gemini")
    llm = _SequenceLLM(
        [
            AdapterBadResponse("PFA-DEMO-003", message="simulated transient failure"),
            {
                "response": "Samajh gayi, dhanyavaad.",
                "detected_language": "hi",
                "topics": ["billing"],
                "next_action": "follow_up",
                "end_call": False,
            },
        ]
    )
    registry = _registry(llm)

    result = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Billing thodi confusing thi."
    )
    assert result.response_text == "Samajh gayi, dhanyavaad."
    assert llm.call_count == 2  # first attempt failed, second succeeded — no fallback needed

    timeline = await svc.get_timeline(superadmin_session, started.call_id)
    error_events = [e for e in timeline if e.type == "ERROR"]
    assert len(error_events) == 1
    assert error_events[0].data["attempt"] == 1


async def test_llm_failure_twice_falls_back_and_call_survives(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, provider="gemini")
    llm = _SequenceLLM(
        [
            {"response": "bad", "detected_language": "not-a-real-language"},  # fails validation
            AdapterBadResponse("PFA-DEMO-003", message="simulated second failure"),
        ]
    )
    registry = _registry(llm)

    result = await svc.submit_turn(
        superadmin_session, registry, started.call_id, "gemini", "Kuch samajh nahi aaya."
    )
    # Session survives with the catalogued fallback response — never an unhandled crash.
    assert "samajh nahi aaya" in result.response_text
    assert result.end_call is False

    timeline = await svc.get_timeline(superadmin_session, started.call_id)
    error_events = [e for e in timeline if e.type == "ERROR"]
    assert len(error_events) == 3  # attempt 1, attempt 2, final "failed twice" event


async def test_max_turns_ceiling_ends_call_even_if_llm_never_asks(
    superadmin_session: AsyncSession,
) -> None:
    started = await svc.start_call(superadmin_session, provider="gemini")
    # MAX_TURNS = 8 (domain/conversation_topics.py) — the LLM says end_call=False every time.
    llm = _SequenceLLM(
        [
            {
                "response": f"turn {i}",
                "detected_language": "hi",
                "topics": [],
                "next_action": "follow_up",
                "end_call": False,
            }
            for i in range(8)
        ]
    )
    registry = _registry(llm)

    result = None
    for i in range(8):
        result = await svc.submit_turn(
            superadmin_session, registry, started.call_id, "gemini", f"patient turn {i}"
        )
    assert result is not None
    assert result.end_call is True  # forced by the MAX_TURNS ceiling, not the LLM's own signal
