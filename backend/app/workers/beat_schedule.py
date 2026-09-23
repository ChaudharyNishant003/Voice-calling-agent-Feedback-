"""Celery Beat schedule (SFTP poll, dial ticks, SLA ticks, digests, retention —
docs/01_ARCHITECTURE.md §2). Entries are added alongside each owning task starting Sprint 1.
"""

from __future__ import annotations

BEAT_SCHEDULE: dict[str, dict[str, object]] = {}
