"""Celery Beat schedule (SFTP poll, dial ticks, SLA ticks, digests, retention —
docs/01_ARCHITECTURE.md §2). Entries are added alongside each owning task starting Sprint 1.
"""

from __future__ import annotations

from celery.schedules import crontab

BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "verify-audit-chain-nightly": {
        "task": "app.workers.tasks.audit.verify_audit_chain",
        # doc 07 §6 "nightly job"; 03:00 UTC chosen arbitrarily as an off-peak hour.
        "schedule": crontab(hour=3, minute=0),
    },
}
