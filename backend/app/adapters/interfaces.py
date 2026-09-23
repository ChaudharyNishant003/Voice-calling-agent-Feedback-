"""Vendor-agnostic Protocols (docs/01_ARCHITECTURE.md §4).

Business code (`app.domain`, `app.services`) depends only on these — never on a vendor SDK
(CLAUDE.md §4 rule 2, enforced by the import-linter contracts in pyproject.toml). Every adapter
method has a timeout, raises only `AdapterError` subclasses (doc 06 error catalogue), and emits an
`adapter.call` event with latency + cost units (see `app.core.observability`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

# ---------- Telephony ----------


@dataclass(frozen=True)
class PlaceCallRequest:
    call_id: str
    to_e164: str
    from_cli: str
    answer_url: str
    status_callback_url: str
    machine_detection: bool = True
    ring_timeout_s: int = 30


@dataclass(frozen=True)
class PlaceCallResult:
    provider_call_id: str
    accepted_at: datetime


@dataclass(frozen=True)
class CallStatusEvent:
    provider_call_id: str
    status: str
    reason: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


class TelephonyAdapter(Protocol):
    async def place_call(self, req: PlaceCallRequest) -> PlaceCallResult: ...
    async def hangup(self, provider_call_id: str) -> None: ...
    async def transfer(self, provider_call_id: str, to_e164: str) -> None: ...
    async def bridge_to_media(self, provider_call_id: str, sip_uri: str) -> None: ...
    def parse_status_webhook(
        self, payload: dict[str, object], headers: dict[str, str]
    ) -> CallStatusEvent: ...
    def verify_webhook_signature(
        self, payload: bytes, headers: dict[str, str], url: str
    ) -> bool: ...


# ---------- STT ----------


@dataclass(frozen=True)
class Transcript:
    text: str
    is_final: bool
    confidence: float
    language: str | None
    start_ms: int
    end_ms: int


class STTStream(Protocol):
    async def push_audio(self, pcm16_8k: bytes) -> None: ...
    def results(self) -> AsyncIterator[Transcript]: ...
    async def close(self) -> None: ...


class STTAdapter(Protocol):
    async def stream_open(
        self,
        languages: list[str],
        sample_rate: int = 8000,
        keywords: list[str] | None = None,
    ) -> STTStream: ...


# ---------- LLM ----------


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, object]
    raw_text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int


class LLMAdapter(Protocol):
    async def complete(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult: ...
    async def classify(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult: ...
    async def extract(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult: ...
    async def summarise(
        self, prompt_id: str, variables: dict[str, object], *, timeout_s: float
    ) -> LLMResult: ...


# ---------- TTS ----------


class TTSAdapter(Protocol):
    def synthesise_stream(
        self, text: str, language: str, voice_id: str, speaking_rate: float = 1.0
    ) -> AsyncIterator[bytes]: ...
    async def synthesise_cached(self, clip_key: str) -> bytes: ...


# ---------- Notifications ----------


class NotificationAdapter(Protocol):
    async def send_email(
        self, to: list[str], subject: str, html: str, text: str, idempotency_key: str
    ) -> str: ...
    async def send_webhook(
        self, url: str, payload: dict[str, object], secret: str, idempotency_key: str
    ) -> int: ...
    async def send_message(
        self,
        channel: Literal["sms", "whatsapp"],
        to_e164: str,
        template_id: str,
        variables: dict[str, object],
    ) -> str: ...  # Phase 2


# ---------- Storage ----------


class ObjectStorageAdapter(Protocol):
    async def put(
        self, key: str, data: bytes, content_type: str, retention_until: datetime
    ) -> str: ...
    async def signed_get_url(self, key: str, ttl_s: int = 300) -> str: ...
    async def delete(self, key: str) -> None: ...
