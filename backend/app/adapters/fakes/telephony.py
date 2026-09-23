"""Deterministic fake telephony adapter (docs/08_TESTING_STRATEGY.md §2).

Outcomes are scripted per `to_e164` so tests and the text-mode call simulator can drive any
scenario (answer, busy, no_answer, voicemail, mid-call drop) without a real Plivo account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.adapters.interfaces import CallStatusEvent, PlaceCallRequest, PlaceCallResult
from app.core.ids import new_id

Outcome = Literal["answer", "busy", "no_answer", "voicemail", "failed"]


@dataclass
class ScriptedOutcome:
    outcome: Outcome = "answer"
    drop_at_s: int | None = None


class FakeTelephony:
    def __init__(self) -> None:
        self.scripts: dict[str, ScriptedOutcome] = {}
        self.placed_calls: list[PlaceCallRequest] = []
        self.hangups: list[str] = []
        self.transfers: list[tuple[str, str]] = []
        self.bridges: list[tuple[str, str]] = []
        self._fail_place_call = False

    def script(self, to_e164: str, outcome: Outcome, *, drop_at_s: int | None = None) -> None:
        self.scripts[to_e164] = ScriptedOutcome(outcome=outcome, drop_at_s=drop_at_s)

    def inject_place_call_failure(self, enabled: bool = True) -> None:
        self._fail_place_call = enabled

    async def place_call(self, req: PlaceCallRequest) -> PlaceCallResult:
        if self._fail_place_call:
            from app.core.errors import AdapterTimeout

            raise AdapterTimeout("PFA-TEL-001", message="fake place_call failure injected")

        self.placed_calls.append(req)
        return PlaceCallResult(
            provider_call_id=new_id("call") + "_provider", accepted_at=datetime.now(UTC)
        )

    async def hangup(self, provider_call_id: str) -> None:
        self.hangups.append(provider_call_id)

    async def transfer(self, provider_call_id: str, to_e164: str) -> None:
        self.transfers.append((provider_call_id, to_e164))

    async def bridge_to_media(self, provider_call_id: str, sip_uri: str) -> None:
        self.bridges.append((provider_call_id, sip_uri))

    def parse_status_webhook(
        self, payload: dict[str, object], headers: dict[str, str]
    ) -> CallStatusEvent:
        reason = payload.get("reason")
        return CallStatusEvent(
            provider_call_id=str(payload.get("provider_call_id", "")),
            status=str(payload.get("status", "unknown")),
            reason=reason if isinstance(reason, str) else None,
            raw=payload,
        )

    def verify_webhook_signature(self, payload: bytes, headers: dict[str, str], url: str) -> bool:
        return headers.get("X-Fake-Signature") == "valid"

    def outcome_for(self, to_e164: str) -> ScriptedOutcome:
        return self.scripts.get(to_e164, ScriptedOutcome())
