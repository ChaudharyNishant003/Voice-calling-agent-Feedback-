"""Real OpenAI LLMAdapter implementation (Demo MVP — new adapter folder, per
`adapters/registry.py`'s documented pattern: "Adding a new provider is: new adapter folder + a
registry entry — zero changes to domain/services"). Uses the `openai` SDK's Responses API
(`AsyncOpenAI().responses.parse`, verified against the installed SDK), which returns an already-
schema-validated `.output_parsed` — no manual `model_validate_json` step needed, unlike Gemini's.

See `adapters/gemini/llm.py`'s module docstring for why error codes are `PFA-DEMO-0xx`, not
`PFA-LLM-0xx`.
"""

from __future__ import annotations

import time

import openai

from app.adapters.interfaces import LLMResult
from app.core.errors import AdapterAuthError, AdapterBadResponse, AdapterError, AdapterTimeout
from app.services.demo_llm_schema import DemoTurnResponse

_PROMPT_SCHEMAS = {"demo_feedback_turn": DemoTurnResponse}


class OpenAILLM:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
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
            response = await self._client.responses.parse(
                model=self._model,
                instructions=system_instruction,
                input=input_transcript,
                text_format=schema,
                timeout=timeout_s,
            )
        except openai.AuthenticationError as exc:
            raise AdapterAuthError(
                "PFA-DEMO-002", message="OpenAI rejected the API key.", cause=exc
            ) from exc
        except openai.APITimeoutError as exc:
            raise AdapterTimeout(
                "PFA-DEMO-005", message="OpenAI request timed out.", cause=exc
            ) from exc
        except openai.APIError as exc:
            raise AdapterBadResponse(
                "PFA-DEMO-003", message=f"OpenAI request failed: {exc}", cause=exc
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        parsed = response.output_parsed
        if parsed is None:
            raise AdapterBadResponse(
                "PFA-DEMO-004", message="OpenAI returned no parsed structured output."
            )

        usage = getattr(response, "usage", None)
        return LLMResult(
            data=parsed.model_dump(),
            raw_text=response.output_text or "",
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
    like `_run` above, so `provider_settings_service` can treat both providers the same way.
    """
    client = openai.AsyncOpenAI(api_key=api_key)
    try:
        await client.responses.create(model=model, input="ping", timeout=10.0)
    except openai.AuthenticationError as exc:
        raise AdapterAuthError(
            "PFA-DEMO-002", message="OpenAI rejected the API key.", cause=exc
        ) from exc
    except AdapterError:
        raise
    except Exception as exc:  # SDK-internal errors (network, etc.) - still a clear test failure
        raise AdapterBadResponse(
            "PFA-DEMO-003", message=f"OpenAI key test failed: {exc}", cause=exc
        ) from exc
