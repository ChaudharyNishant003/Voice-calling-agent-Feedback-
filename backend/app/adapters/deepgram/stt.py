"""Real Deepgram Nova-3 STTAdapter implementation — Sprint 3 (docs/11_BUILD_PLAN.md S3.2).

Not implemented in Sprint 0: only fakes (`app.adapters.fakes.FakeSTT`) are wired up until
credentials exist and this adapter is built against `app.adapters.interfaces.STTAdapter`.
"""

from __future__ import annotations


class DeepgramSTT:
    def __init__(self, *, api_key: str) -> None:
        raise NotImplementedError("Deepgram adapter lands in Sprint 3 (S3.2)")
