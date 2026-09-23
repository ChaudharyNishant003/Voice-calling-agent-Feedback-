"""Real Gemini Flash LLMAdapter implementation — Sprint 4 (docs/11_BUILD_PLAN.md S4.1).

Not implemented in Sprint 0: only fakes (`app.adapters.fakes.FakeLLM`) are wired up until
credentials exist and this adapter is built against `app.adapters.interfaces.LLMAdapter`.
"""

from __future__ import annotations


class GeminiLLM:
    def __init__(self, *, api_key: str) -> None:
        raise NotImplementedError("Gemini adapter lands in Sprint 4 (S4.1)")
