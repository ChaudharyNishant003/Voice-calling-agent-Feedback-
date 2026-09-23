"""Deterministic fake TTS adapter. Returns silent PCM of text-length-proportional duration, with
failure injection (docs/08_TESTING_STRATEGY.md §2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.errors import AdapterTimeout

_SAMPLE_RATE = 8000
_BYTES_PER_SAMPLE = 2
_MS_PER_CHAR = 60  # rough silent-audio duration proxy, good enough for test assertions


def _silence(duration_ms: int) -> bytes:
    n_samples = int(_SAMPLE_RATE * duration_ms / 1000)
    return b"\x00" * (n_samples * _BYTES_PER_SAMPLE)


class FakeTTS:
    def __init__(self) -> None:
        self.cached_clips: dict[str, bytes] = {}
        self._fail_synthesise = False
        self.synthesise_calls: list[tuple[str, str]] = []

    def register_cached_clip(self, clip_key: str, data: bytes) -> None:
        self.cached_clips[clip_key] = data

    def inject_synthesise_failure(self, enabled: bool = True) -> None:
        self._fail_synthesise = enabled

    async def synthesise_stream(
        self, text: str, language: str, voice_id: str, speaking_rate: float = 1.0
    ) -> AsyncIterator[bytes]:
        self.synthesise_calls.append((text, language))
        if self._fail_synthesise:
            raise AdapterTimeout("PFA-TTS-001", message="fake TTS stream failure injected")

        duration_ms = max(200, int(len(text) * _MS_PER_CHAR / max(speaking_rate, 0.1)))
        chunk = _silence(min(duration_ms, 400))
        remaining = duration_ms
        while remaining > 0:
            yield chunk
            remaining -= 400

    async def synthesise_cached(self, clip_key: str) -> bytes:
        if clip_key not in self.cached_clips:
            raise AdapterTimeout("PFA-TTS-002", message=f"no cached clip for {clip_key!r}")
        return self.cached_clips[clip_key]
