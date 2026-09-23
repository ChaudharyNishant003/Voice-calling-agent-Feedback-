"""Real Plivo TelephonyAdapter implementation — Sprint 2 (docs/11_BUILD_PLAN.md S2.3).

Not implemented in Sprint 0: only fakes (`app.adapters.fakes.FakeTelephony`) are wired up until
credentials exist and this adapter is built against `app.adapters.interfaces.TelephonyAdapter`.
"""

from __future__ import annotations


class PlivoTelephony:
    def __init__(self, *, auth_id: str, auth_token: str) -> None:
        raise NotImplementedError("Plivo adapter lands in Sprint 2 (S2.3)")
