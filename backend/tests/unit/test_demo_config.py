"""Unit: `Settings.validate_startup()`'s demo-mode production guard (PFA-SYS-010, Demo MVP spec
§15) — fail-closed by construction, matching `require_demo_mode`'s own belt-and-suspenders check.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_demo_mode_refused_in_production() -> None:
    settings = Settings(
        app_env="production",
        demo_mode=True,
        telephony_provider="plivo",
        stt_provider="deepgram",
        llm_provider="gemini",
        tts_provider="cartesia",
        test_allowlist_e164="+911234567890",
    )
    with pytest.raises(RuntimeError, match="PFA-SYS-010"):
        settings.validate_startup()


def test_demo_mode_allowed_outside_production() -> None:
    settings = Settings(app_env="local", demo_mode=True)
    settings.validate_startup()  # must not raise


def test_demo_mode_off_does_not_affect_production_startup() -> None:
    settings = Settings(
        app_env="production",
        demo_mode=False,
        telephony_provider="plivo",
        stt_provider="deepgram",
        llm_provider="gemini",
        tts_provider="cartesia",
        test_allowlist_e164="+911234567890",
    )
    settings.validate_startup()  # must not raise — demo_mode=False is the safe default
