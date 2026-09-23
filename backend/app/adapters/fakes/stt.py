"""Deterministic fake STT adapter. Yields scripted transcripts with configurable confidence/
latency/language, and can inject a mid-stream failure (docs/08_TESTING_STRATEGY.md §2).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.adapters.interfaces import Transcript
from app.core.errors import AdapterBadResponse


@dataclass
class ScriptedTranscript:
    text: str
    is_final: bool = True
    confidence: float = 0.95
    language: str | None = "en"
    start_ms: int = 0
    end_ms: int = 0
    delay_s: float = 0.0


class FakeSTTStream:
    def __init__(self, script: list[ScriptedTranscript], *, fail_after: int | None = None) -> None:
        self._script = script
        self._fail_after = fail_after
        self._pushed_audio_frames = 0
        self._closed = False

    async def push_audio(self, pcm16_8k: bytes) -> None:
        self._pushed_audio_frames += 1

    async def results(self) -> AsyncIterator[Transcript]:
        for i, item in enumerate(self._script):
            if self._fail_after is not None and i >= self._fail_after:
                raise AdapterBadResponse("PFA-STT-001", message="fake STT stream failure injected")
            if item.delay_s:
                await asyncio.sleep(item.delay_s)
            yield Transcript(
                text=item.text,
                is_final=item.is_final,
                confidence=item.confidence,
                language=item.language,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
            )

    async def close(self) -> None:
        self._closed = True


class FakeSTT:
    def __init__(self) -> None:
        self.scripts_by_call: dict[str, list[ScriptedTranscript]] = {}
        self.fail_after_by_call: dict[str, int] = {}
        self.opened_streams: list[FakeSTTStream] = []

    def script(self, call_id: str, transcripts: list[ScriptedTranscript]) -> None:
        self.scripts_by_call[call_id] = transcripts

    def inject_stream_failure(self, call_id: str, *, after_n_transcripts: int) -> None:
        self.fail_after_by_call[call_id] = after_n_transcripts

    async def stream_open(
        self,
        languages: list[str],
        sample_rate: int = 8000,
        keywords: list[str] | None = None,
        *,
        call_id: str = "default",
    ) -> FakeSTTStream:
        stream = FakeSTTStream(
            self.scripts_by_call.get(call_id, []),
            fail_after=self.fail_after_by_call.get(call_id),
        )
        self.opened_streams.append(stream)
        return stream
