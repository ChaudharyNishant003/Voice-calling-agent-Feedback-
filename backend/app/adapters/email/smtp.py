"""Real SMTP NotificationAdapter implementation — Sprint 5 (docs/11_BUILD_PLAN.md S5.5).

Local dev already has a real (non-fake) email path via `mailpit` at the SMTP_URL in .env.example —
this module is the production-grade adapter with retries/backoff per doc 06 §3, built in Sprint 5.
"""

from __future__ import annotations


class SMTPNotifier:
    def __init__(self, *, smtp_url: str) -> None:
        raise NotImplementedError("SMTP notifier lands in Sprint 5 (S5.5)")
