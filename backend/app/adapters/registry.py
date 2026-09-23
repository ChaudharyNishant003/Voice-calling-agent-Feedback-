"""Adapter registry: resolves an adapter by (capability, language, account) from config
(docs/01_ARCHITECTURE.md §4.1), and wraps every adapter call in a circuit breaker
(docs/06_ERROR_HANDLING_AND_MESSAGES.md §3 — open after 5 failures/30s, half-open after 30s).

Adding a new STT/LLM/TTS provider is: new adapter folder + an entry in `STTRouting` (or the
LLM/TTS equivalents) — zero changes to `app.domain` or `app.services`, enforced by the
import-linter contracts in pyproject.toml.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pybreaker

from app.adapters.fakes import FakeLLM, FakeSTT, FakeTelephony, FakeTTS
from app.adapters.interfaces import LLMAdapter, STTAdapter, TelephonyAdapter, TTSAdapter
from app.core.errors import AdapterError

BREAKER_FAIL_MAX = 5
BREAKER_RESET_TIMEOUT_S = 30


def new_breaker(name: str) -> pybreaker.CircuitBreaker:
    """Only AdapterError (and subclasses) count as breaker failures — never business exceptions."""
    return pybreaker.CircuitBreaker(
        fail_max=BREAKER_FAIL_MAX,
        reset_timeout=BREAKER_RESET_TIMEOUT_S,
        exclude=[lambda exc: not isinstance(exc, AdapterError)],
        name=name,
    )


@dataclass
class STTRouting:
    """docs/01_ARCHITECTURE.md §4.1 — regional slot is present but empty (Open Question #5 default:
    EN + HI only until a pilot's regional language is chosen)."""

    default: str = "deepgram"
    by_language: dict[str, str] = field(
        default_factory=lambda: {"en": "deepgram", "hi": "deepgram", "hi-en": "deepgram"}
    )
    low_confidence_threshold: float = 0.55

    def provider_for(self, language: str) -> str:
        return self.by_language.get(language, self.default)


class AdapterRegistry[T]:
    """Holds one adapter instance per provider name plus a breaker per provider."""

    def __init__(self) -> None:
        self._adapters: dict[str, T] = {}
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {}

    def register(self, provider: str, adapter: T) -> None:
        self._adapters[provider] = adapter
        self._breakers[provider] = new_breaker(provider)

    def get(self, provider: str) -> T:
        if provider not in self._adapters:
            raise KeyError(f"no adapter registered for provider {provider!r}")
        return self._adapters[provider]

    def breaker(self, provider: str) -> pybreaker.CircuitBreaker:
        return self._breakers[provider]


def build_fake_registries() -> tuple[
    AdapterRegistry[TelephonyAdapter],
    AdapterRegistry[STTAdapter],
    AdapterRegistry[LLMAdapter],
    AdapterRegistry[TTSAdapter],
]:
    """Local dev / CI wiring: every capability resolves to its fake (doc 10 — TELEPHONY_PROVIDER=
    fake etc. by default). Sprint 2-4 add a `build_real_registries()` once vendor adapters exist.
    """
    telephony = AdapterRegistry[TelephonyAdapter]()
    telephony.register("fake", FakeTelephony())

    stt = AdapterRegistry[STTAdapter]()
    stt.register("fake", FakeSTT())

    llm = AdapterRegistry[LLMAdapter]()
    llm.register("fake", FakeLLM())

    tts = AdapterRegistry[TTSAdapter]()
    tts.register("fake", FakeTTS())

    return telephony, stt, llm, tts
