"""Injectable clock. All business code reads time through a Clock, never `datetime.now()` directly,
so tests can freeze it (doc 08 §2 — FrozenClock) for window/SLA/retention tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock time, always UTC (CLAUDE.md §8 — store timestamptz UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests. Starts at `start` (default: a fixed UTC instant) and only
    advances when `advance()` is called explicitly.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, when: datetime) -> None:
        self._now = when
