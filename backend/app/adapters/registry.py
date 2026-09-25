"""Adapter registry: resolves an adapter by (capability, language, account) from config
(docs/01_ARCHITECTURE.md §4.1), and wraps every adapter call in a circuit breaker
(docs/06_ERROR_HANDLING_AND_MESSAGES.md §3 — open after 5 failures/30s, half-open after 30s).

Adding a new STT/LLM/TTS provider is: new adapter folder + an entry in `STTRouting` (or the
LLM/TTS equivalents) — zero changes to `app.domain` or `app.services`, enforced by the
import-linter contracts in pyproject.toml.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

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


async def call_with_breaker[T](
    breaker: pybreaker.CircuitBreaker,
    func: Callable[..., Awaitable[T]],
    *args: object,
    **kwargs: object,
) -> T:
    """Runs an async adapter call through `breaker`'s closed/open/half-open state machine.

    Not `breaker.call_async(...)`: confirmed by direct testing against the installed `pybreaker`
    (1.4.1), that method's `@gen.coroutine` wrapper references `tornado.gen`, which is never
    imported when `tornado` isn't installed — every call raises `NameError: name 'gen' is not
    defined`, regardless of the wrapped function. Adding `tornado` as a dependency just to satisfy
    a legacy Tornado-coroutine compatibility shim (in a codebase that is otherwise 100% asyncio) is
    the wrong trade; and even with `tornado` installed, `CircuitOpenState.before_call` calls back
    into `breaker.call()` — the *sync* dispatch path — on the half-open trial, which would silently
    mishandle an async `func` (return an un-awaited coroutine as if it were the result).

    This reimplements the same behavior natively: the open-state timeout check + half-open
    transition is hand-written (mirroring `CircuitOpenState.before_call` minus its broken
    recursion), and success/failure recording reuses `CircuitBreakerState._handle_success`/
    `_handle_error` directly — those particular methods are plain synchronous Python with no
    tornado dependency, and are exactly what `call_async` itself would have delegated to. Verified
    against the real library: closed -> open after `fail_max` failures, fail-fast while open,
    half-open trial after `reset_timeout`, and re-open on a failed trial.
    """
    if breaker.current_state == "open":
        storage = breaker._state_storage  # the one documented extension seam pybreaker exposes
        opened_at = storage.opened_at
        timeout_elapsed = (
            opened_at is not None
            and (datetime.now(UTC) - opened_at).total_seconds() >= breaker.reset_timeout
        )
        if not timeout_elapsed:
            raise pybreaker.CircuitBreakerError(
                "Timeout not elapsed yet, circuit breaker still open"
            )
        breaker.half_open()

    for listener in breaker.listeners:
        listener.before_call(breaker, func, *args, **kwargs)

    try:
        result = await func(*args, **kwargs)
    except BaseException as exc:
        breaker.state._handle_error(exc)  # always raises — see docstring
        raise AssertionError("unreachable: _handle_error always raises") from exc
    else:
        breaker.state._handle_success()
        return result


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

    def has(self, provider: str) -> bool:
        return provider in self._adapters

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


# Demo MVP's real-LLM registry builder deliberately does NOT live here, even though this looks
# like the obvious place for it: `registry.py` is imported by `app.services` (e.g.
# `services/demo_conversation_service.py`, for the generic `AdapterRegistry` type), and the
# import-linter's "services never import vendor SDKs" contract checks *transitive* reachability —
# if this module imported `app.adapters.gemini`/`openai` (even lazily, inside a function), every
# service that imports `AdapterRegistry` from here would become transitively "importing Gemini",
# and the contract correctly flags that. Real vendor adapter construction for the demo instead
# happens in `api/v1/demo.py`, which isn't restricted by either import-linter contract — it builds
# an `AdapterRegistry[LLMAdapter]()` directly via the public `register()` method used above.
