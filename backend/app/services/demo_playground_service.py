"""Playground orchestration — one function per pipeline stage (see docs/11_BUILD_PLAN.md's Demo MVP
section for the full stage list and rationale). Pure I/O + orchestration, no persistence: unlike
`demo_conversation_service.py`, nothing here writes to the database — the Playground is a stateless
what-if tool, deliberately kept separate from and non-destructive to the real demo call.

The four LLM-stage functions take an already-constructed `adapter: LLMAdapter` (built in
`api/v1/demo.py`, which is the one place allowed to import vendor adapter modules — see
`adapters/registry.py`'s note on the import-linter's transitive-reachability contract for why).
Unlike the live call's `_call_llm_with_retry`, there is no retry-then-fallback here: a Playground
run is a deliberate one-shot test, and papering over a failure would hide exactly the kind of signal
someone comparing models is looking for. Malformed structured output is re-raised as the existing
`AdapterBadResponse("PFA-DEMO-004", ...)`; genuine adapter failures (auth/timeout/bad response)
propagate as-is — both are already-catalogued `PFAError` subclasses that FastAPI's installed error
handlers render correctly without any Playground-specific error code.

The three deterministic stages are thin, direct wrappers around the existing pure domain functions
— kept in this service layer rather than called straight from the API router, matching CLAUDE.md's
"never put business logic in routers" even though the wrapping is trivial.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.adapters.interfaces import LLMAdapter
from app.core.errors import AdapterBadResponse
from app.domain.conversation_language import LanguageFamily, LanguageState, decide_language
from app.domain.conversation_topics import Topic, TopicState, record_topics, should_end
from app.services.demo_playground_prompts import (
    build_end_judgment_prompt,
    build_language_detection_prompt,
    build_response_generation_prompt,
    build_topic_extraction_prompt,
)
from app.services.demo_playground_schemas import (
    EndJudgmentResult,
    LanguageDetectionResult,
    ResponseGenerationResult,
    TopicExtractionResult,
)

# See demo_conversation_service.py's matching constant for the latency investigation this is
# based on.
_LLM_TIMEOUT_S = 12.0


@dataclass(frozen=True)
class LLMStepOutcome[T]:
    parsed: T
    raw_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str


async def _run_llm_step[T: BaseModel](
    adapter: LLMAdapter, prompt_id: str, schema: type[T], system_instruction: str, input_text: str
) -> LLMStepOutcome[T]:
    result = await adapter.complete(
        prompt_id,
        {"system_instruction": system_instruction, "input_transcript": input_text},
        timeout_s=_LLM_TIMEOUT_S,
    )
    try:
        parsed = schema.model_validate(result.data)
    except PydanticValidationError as exc:
        raise AdapterBadResponse(
            "PFA-DEMO-004", message=f"Model returned malformed structured output: {exc}", cause=exc
        ) from exc
    return LLMStepOutcome(
        parsed=parsed,
        raw_text=result.raw_text,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
    )


async def run_language_detection(
    adapter: LLMAdapter, *, patient_text: str
) -> LLMStepOutcome[LanguageDetectionResult]:
    system, input_text = build_language_detection_prompt(patient_text)
    return await _run_llm_step(
        adapter, "playground_language_detection", LanguageDetectionResult, system, input_text
    )


async def run_topic_extraction(
    adapter: LLMAdapter, *, patient_text: str
) -> LLMStepOutcome[TopicExtractionResult]:
    system, input_text = build_topic_extraction_prompt(patient_text)
    return await _run_llm_step(
        adapter, "playground_topic_extraction", TopicExtractionResult, system, input_text
    )


async def run_end_judgment(
    adapter: LLMAdapter, *, patient_text: str, topics_covered: frozenset[str], turn_count: int
) -> LLMStepOutcome[EndJudgmentResult]:
    system, input_text = build_end_judgment_prompt(
        patient_text=patient_text, topics_covered=topics_covered, turn_count=turn_count
    )
    return await _run_llm_step(
        adapter, "playground_end_judgment", EndJudgmentResult, system, input_text
    )


async def run_response_generation(
    adapter: LLMAdapter,
    *,
    hospital_name: str,
    agent_name: str,
    voice_gender: str,
    locked_language: str | None,
    topics_covered: frozenset[str],
    is_ending: bool,
    patient_text: str,
) -> LLMStepOutcome[ResponseGenerationResult]:
    system, input_text = build_response_generation_prompt(
        hospital_name=hospital_name,
        agent_name=agent_name,
        voice_gender=voice_gender,
        locked_language=locked_language,
        topics_covered=topics_covered,
        is_ending=is_ending,
        patient_text=patient_text,
    )
    return await _run_llm_step(
        adapter, "playground_response_generation", ResponseGenerationResult, system, input_text
    )


# "hi"/"hinglish" both mean the same locked family; only an explicit ask carries "hi"/"en" as a
# genuine switch target. Same mapping `demo_conversation_service.py` uses for the live call — kept
# local here rather than imported, since it's three lines and importing it would couple this
# stateless, DB-free service to that one's module for no real reuse benefit.
_DETECTED_TO_FAMILY = {
    "hi": LanguageFamily.hindi_hinglish,
    "hinglish": LanguageFamily.hindi_hinglish,
    "en": LanguageFamily.english,
}
_REQUESTED_TO_FAMILY = {"hi": LanguageFamily.hindi_hinglish, "en": LanguageFamily.english}


@dataclass(frozen=True)
class LanguageLockOutcome:
    locked_language: str | None
    consecutive_other_count: int
    switched: bool


def run_language_lock(
    *,
    detected_language: str,
    requested_language: str | None,
    prior_locked_language: str | None,
    prior_streak: int,
) -> LanguageLockOutcome:
    state = LanguageState(
        locked=LanguageFamily(prior_locked_language) if prior_locked_language else None,
        consecutive_other_count=prior_streak,
    )
    requested_family = _REQUESTED_TO_FAMILY.get(requested_language) if requested_language else None
    decision = decide_language(
        state, _DETECTED_TO_FAMILY[detected_language], requested=requested_family
    )
    return LanguageLockOutcome(
        locked_language=decision.state.locked.value if decision.state.locked else None,
        consecutive_other_count=decision.state.consecutive_other_count,
        switched=decision.switched,
    )


@dataclass(frozen=True)
class TopicTrackingOutcome:
    topics_covered: list[str]


def run_topic_tracking(
    *, topics_mentioned: list[str], prior_topics_covered: list[str]
) -> TopicTrackingOutcome:
    mentioned = frozenset(Topic(t) for t in topics_mentioned)
    prior = frozenset(Topic(t) for t in prior_topics_covered)
    new_state = record_topics(TopicState(covered=prior), mentioned)
    return TopicTrackingOutcome(topics_covered=sorted(t.value for t in new_state.covered))


def run_end_ceiling(*, turn_count: int, llm_wants_to_end: bool) -> bool:
    return should_end(turn_count=turn_count, llm_wants_to_end=llm_wants_to_end)
