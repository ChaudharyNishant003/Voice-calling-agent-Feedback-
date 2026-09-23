import pybreaker
import pytest

from app.adapters.registry import BREAKER_FAIL_MAX, STTRouting, build_fake_registries, new_breaker
from app.core.errors import AdapterTimeout


def test_stt_routing_defaults_regional_slot_empty() -> None:
    routing = STTRouting()
    assert routing.provider_for("en") == "deepgram"
    assert routing.provider_for("hi") == "deepgram"
    assert routing.provider_for("hi-en") == "deepgram"
    # No regional language configured yet (Open Question #5 default) — falls back to default.
    assert routing.provider_for("ta") == routing.default


def test_build_fake_registries_resolves_every_capability() -> None:
    telephony, stt, llm, tts = build_fake_registries()
    assert telephony.get("fake") is not None
    assert stt.get("fake") is not None
    assert llm.get("fake") is not None
    assert tts.get("fake") is not None


def test_unregistered_provider_raises_key_error() -> None:
    telephony, _, _, _ = build_fake_registries()
    with pytest.raises(KeyError):
        telephony.get("plivo")


def test_breaker_opens_after_fail_max_adapter_errors() -> None:
    breaker = new_breaker("test-provider")

    def _fail() -> None:
        raise AdapterTimeout("PFA-TEL-001")

    # The Nth failure trips the breaker open, so pybreaker re-raises CircuitBreakerError on that
    # call instead of the underlying AdapterTimeout.
    for _ in range(BREAKER_FAIL_MAX - 1):
        with pytest.raises(AdapterTimeout):
            breaker.call(_fail)

    with pytest.raises(pybreaker.CircuitBreakerError):
        breaker.call(_fail)

    assert breaker.current_state == "open"


def test_breaker_ignores_non_adapter_errors() -> None:
    breaker = new_breaker("test-provider-2")

    def _fail() -> None:
        raise ValueError("not an adapter error")

    for _ in range(BREAKER_FAIL_MAX + 2):
        with pytest.raises(ValueError):
            breaker.call(_fail)

    assert breaker.current_state == "closed"
