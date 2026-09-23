"""Real Cartesia Sonic TTSAdapter implementation — Sprint 3 (docs/11_BUILD_PLAN.md S3.3).

Not implemented in Sprint 0: only fakes (`app.adapters.fakes.FakeTTS`) are wired up until
credentials exist and this adapter is built against `app.adapters.interfaces.TTSAdapter`.
"""

from __future__ import annotations


class CartesiaTTS:
    def __init__(self, *, api_key: str) -> None:
        raise NotImplementedError("Cartesia adapter lands in Sprint 3 (S3.3)")
