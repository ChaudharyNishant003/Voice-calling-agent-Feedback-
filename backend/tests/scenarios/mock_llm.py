"""Deterministic stub `LLMAdapter` for `--mock-llm` scenario runs (PRD v2 Phase 7 decision #4: build
the full harness, but CI only needs to exercise the plumbing deterministically — real conversation
quality is checked by the small real-API sample instead, per `runner.py`'s module docstring).

Same shape as `tests/integration/test_pfa_call_service_persistence.py`'s `_SequenceLLM`, with one
difference: running out of queued responses is treated as a scenario-authoring bug (the YAML's
per-turn `contract` entries didn't match how many times the engine actually calls the LLM) and
raises immediately with a diagnostic, rather than an opaque `IndexError` or a guessed default that
would silently mask the mismatch.
"""

from __future__ import annotations

import json

from app.adapters.interfaces import LLMResult

_DEFAULTS: dict[str, object] = {
    "reply_text": "Samajh gayi, dhanyavaad.",
    "language_detected": "hinglish",
}


class ScenarioLLM:
    def __init__(self, contracts: list[dict[str, object]]) -> None:
        self._queue: list[dict[str, object]] = list(contracts)
        self.call_count = 0

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.call_count += 1
        if not self._queue:
            raise AssertionError(
                f"scenario LLM queue exhausted at call #{self.call_count} for prompt {prompt_id!r} "
                "— the scenario declared fewer `contract` entries than the engine actually needed. "
                "Check which turns should short-circuit before the LLM (safety keyword hit, "
                "opt_out/wants_human policy match, `silence`/`stt_error` event_kind, or an "
                "escalate_urgent follow-up turn) and make sure only turns that reach the LLM carry "
                "a `contract`."
            )
        item = {**_DEFAULTS, **self._queue.pop(0)}
        if "proposed_next" not in item:
            raise AssertionError(
                f"scenario contract at call #{self.call_count} is missing required `proposed_next`."
            )
        return LLMResult(
            data=item,
            raw_text=json.dumps(item),
            input_tokens=1,
            output_tokens=1,
            model="scenario-mock",
            latency_ms=1,
        )

    async def classify(self, *args: object, **kwargs: object) -> LLMResult:
        return await self.complete(*args, **kwargs)  # type: ignore[arg-type]

    async def extract(self, *args: object, **kwargs: object) -> LLMResult:
        return await self.complete(*args, **kwargs)  # type: ignore[arg-type]

    async def summarise(self, *args: object, **kwargs: object) -> LLMResult:
        return await self.complete(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def exhausted_cleanly(self) -> bool:
        return len(self._queue) == 0
