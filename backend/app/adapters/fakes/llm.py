"""Deterministic fake LLM adapter. Returns fixture JSON keyed by (prompt_id, input hash); modes:
ok, timeout, malformed, banned_content (docs/08_TESTING_STRATEGY.md §2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from app.adapters.interfaces import LLMResult
from app.core.errors import AdapterTimeout

Mode = Literal["ok", "timeout", "malformed", "banned_content"]


def _input_hash(variables: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(variables, sort_keys=True, default=str).encode()).hexdigest()[
        :16
    ]


class FakeLLM:
    def __init__(self) -> None:
        self._fixtures: dict[tuple[str, str], dict[str, object]] = {}
        self._modes: dict[str, Mode] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def add_fixture(
        self, prompt_id: str, variables: dict[str, object], data: dict[str, object]
    ) -> None:
        self._fixtures[(prompt_id, _input_hash(variables))] = data

    def set_mode(self, prompt_id: str, mode: Mode) -> None:
        self._modes[prompt_id] = mode

    async def _run(
        self, op: str, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        self.calls.append((prompt_id, variables))
        mode = self._modes.get(prompt_id, "ok")

        if mode == "timeout":
            raise AdapterTimeout("PFA-LLM-001", message=f"fake LLM timeout on {op}:{prompt_id}")

        if mode == "malformed":
            return LLMResult(
                data={},
                raw_text="{not valid json",
                input_tokens=10,
                output_tokens=1,
                model="fake-llm",
                latency_ms=5,
            )

        if mode == "banned_content":
            data: dict[str, object] = {"banned": True, "suggestion": "rate us on Google"}
        else:
            data = self._fixtures.get((prompt_id, _input_hash(variables)), {"ok": True})

        return LLMResult(
            data=data,
            raw_text=json.dumps(data),
            input_tokens=10,
            output_tokens=5,
            model="fake-llm",
            latency_ms=5,
        )

    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run("complete", prompt_id, variables, timeout_s=timeout_s)

    async def classify(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run("classify", prompt_id, variables, timeout_s=timeout_s)

    async def extract(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run("extract", prompt_id, variables, timeout_s=timeout_s)

    async def summarise(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult:
        return await self._run("summarise", prompt_id, variables, timeout_s=timeout_s)
