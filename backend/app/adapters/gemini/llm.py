"""Real Gemini LLMAdapter implementation (Demo MVP — replaces the Sprint-0 `NotImplementedError`
stub). Uses the `google-genai` SDK's Interactions API (`client.aio.interactions.create`, verified
against the installed SDK — this is a newer interface than the older `generate_content`/
`GenerativeModel` shape, current as of implementation time per docs.ai.google.dev).

`demo_feedback_turn` is the live call's combined-stage prompt_id; the four `playground_*` ones are
the Playground's narrower, single-stage prompts (`services/demo_playground_service.py`) — both
routes through the exact same `_run()`, since the adapter only ever needs a `(prompt_id,
system_instruction, input_transcript)` triple regardless of which stage it's for. `classify`/
`extract`/`summarise` delegate to the same request path so the adapter is fully `LLMAdapter`-
Protocol-compliant rather than half-stubbed, even though nothing in this MVP calls them yet.

Error codes are `PFA-DEMO-0xx` (docs/06_ERROR_HANDLING_AND_MESSAGES.md), not the existing
`PFA-LLM-0xx` codes — those already have distinct, documented production-call-flow meanings
("in-call timeout", "output failed content guard", "post-call extraction failed") that don't match
these demo-specific failure modes; reusing them would silently overload their meaning.
"""

from __future__ import annotations

import time

from google import genai
from pydantic import BaseModel

from app.adapters.interfaces import LLMResult
from app.core.errors import AdapterAuthError, AdapterBadResponse, AdapterError, AdapterTimeout
from app.services.demo_llm_schema import DemoTurnResponse
from app.services.demo_playground_schemas import (
    EndJudgmentResult,
    LanguageDetectionResult,
    ResponseGenerationResult,
    TopicExtractionResult,
)

# Explicit annotation needed: with a single value type, mypy previously inferred
# `dict[str, type[DemoTurnResponse]]` correctly on its own; with several different Pydantic model
# classes as values it instead infers `dict[str, ModelMetaclass]` (the classes' shared metaclass,
# not their shared base), which breaks every `schema.model_json_schema()`/`model_validate_json()`
# call below.
_PROMPT_SCHEMAS: dict[str, type[BaseModel]] = {
    "demo_feedback_turn": DemoTurnResponse,
    "playground_language_detection": LanguageDetectionResult,
    "playground_topic_extraction": TopicExtractionResult,
    "playground_end_judgment": EndJudgmentResult,
    "playground_response_generation": ResponseGenerationResult,
}


def _map_gemini_error(exc: Exception) -> AdapterError:
    """The Interactions API (`client.aio.interactions.create`) raises from an internal, underscore-
    prefixed exception hierarchy (`google.genai._gaos.lib.compat_errors.*`) that is NOT the public
    `google.genai.errors.ClientError`/`ServerError` classes — confirmed by direct testing against
    the installed SDK, not assumed from docs. Catching those public classes here would silently
    never match anything real this API surface raises. Duck-typing on `status_code` is robust to
    that private hierarchy (and to it changing across SDK versions).

    Google's API is also inconsistent about auth-failure status codes: an invalid key comes back as
    HTTP 400 `INVALID_ARGUMENT`/`API_KEY_INVALID`, not 401/403 — so an invalid-key message is
    treated as an auth failure regardless of status code, not just on 401/403.
    """
    status = getattr(exc, "status_code", None)
    message = str(exc)
    if status in (401, 403) or "API_KEY_INVALID" in message or "API key not valid" in message:
        return AdapterAuthError("PFA-DEMO-002", message="Gemini rejected the API key.", cause=exc)
    if isinstance(status, int) and status >= 500:
        return AdapterTimeout("PFA-DEMO-005", message=f"Gemini server error: {exc}", cause=exc)
    return AdapterBadResponse("PFA-DEMO-003", message=f"Gemini request failed: {exc}", cause=exc)


class GeminiLLM:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def _run(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        schema = _PROMPT_SCHEMAS.get(prompt_id)
        if schema is None:
            raise AdapterBadResponse("PFA-DEMO-001", message=f"unknown prompt_id {prompt_id!r}")

        system_instruction = variables.get("system_instruction")
        input_transcript = variables.get("input_transcript")
        if not isinstance(system_instruction, str) or not isinstance(input_transcript, str):
            raise AdapterBadResponse(
                "PFA-DEMO-001",
                message="variables must include system_instruction/input_transcript",
            )

        started = time.monotonic()
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                system_instruction=system_instruction,
                input=input_transcript,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema.model_json_schema(),
                },
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            raise AdapterTimeout(
                "PFA-DEMO-005", message="Gemini request timed out.", cause=exc
            ) from exc
        except Exception as exc:
            raise _map_gemini_error(exc) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        # `create()`'s declared return type is a union with a streaming variant that has no
        # `output_text`, even though this adapter never passes `stream=True` (so at runtime it's
        # always the plain `Interaction`). The SDK's own `Interaction` name resolves to an
        # unrelated request-side type alias in this version, so `isinstance`/`cast` against it
        # would be actively wrong — `getattr` with a default sidesteps the mismatch entirely and is
        # still a genuine runtime safety net (empty string, not a crash, if the shape is ever
        # unexpected).
        raw_text = getattr(interaction, "output_text", None) or ""
        if not raw_text:
            raise AdapterBadResponse(
                "PFA-DEMO-003", message="Gemini returned no text output."
            )
        try:
            parsed = schema.model_validate_json(raw_text)
        except ValueError as exc:
            raise AdapterBadResponse(
                "PFA-DEMO-004",
                message=f"Gemini returned malformed structured output: {exc}",
                cause=exc,
            ) from exc

        usage = getattr(interaction, "usage", None)
        return LLMResult(
            data=parsed.model_dump(),
            raw_text=raw_text,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            model=self._model,
            latency_ms=latency_ms,
        )

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run(prompt_id, variables, timeout_s=timeout_s)

    async def classify(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run(prompt_id, variables, timeout_s=timeout_s)

    async def extract(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run(prompt_id, variables, timeout_s=timeout_s)

    async def summarise(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run(prompt_id, variables, timeout_s=timeout_s)


async def test_api_key(api_key: str, model: str) -> None:
    """One cheap real call to validate a key — raises AdapterError subclasses on failure, exactly
    like `_run` above, so `provider_settings_service` can treat both the same way.
    """
    client = genai.Client(api_key=api_key)
    try:
        await client.aio.interactions.create(model=model, input="ping", timeout=10.0)
    except TimeoutError as exc:
        raise AdapterTimeout(
            "PFA-DEMO-005", message="Gemini request timed out.", cause=exc
        ) from exc
    except Exception as exc:
        raise _map_gemini_error(exc) from exc
