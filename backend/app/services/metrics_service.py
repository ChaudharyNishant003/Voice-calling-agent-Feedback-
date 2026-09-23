"""`call_events` writer seam (docs/09_OBSERVABILITY_AND_COST.md §2).

The `call_events` table is created by a Sprint 1 migration (docs/11_BUILD_PLAN.md S1.1); this
module gives Sprint 1+ code (dial service, agent runtime, post-call worker) a stable function to
call into today, so nothing has to change shape later — only the body swaps from an in-memory
buffer to a real INSERT once `app.db.models` exists.

Text content is never in events (doc 09 §2) — callers pass structured `data`, not free text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.core.clock import Clock, SystemClock

CallEventType = Literal[
    "call.queued",
    "call.dial_attempt",
    "call.status",
    "state.transition",
    "consent.change",
    "turn.patient",
    "turn.agent",
    "latency.turn",
    "adapter.call",
    "interrupt",
    "safety.trigger",
    "bargein",
    "extraction.result",
    "case.created",
    "cost.final",
]


@dataclass(frozen=True)
class CallEvent:
    call_id: str
    ts: datetime
    type: CallEventType
    data: dict[str, object] = field(default_factory=dict)


class CallEventWriter:
    """In-memory sink until the `call_events` table lands (Sprint 1 S1.1). Same call signature
    either way — Sprint 1+ swaps the body for a repository INSERT, not the callers.
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self.events: list[CallEvent] = []

    def emit(
        self, call_id: str, type: CallEventType, data: dict[str, object] | None = None
    ) -> CallEvent:
        event = CallEvent(call_id=call_id, ts=self._clock.now(), type=type, data=data or {})
        self.events.append(event)
        return event
