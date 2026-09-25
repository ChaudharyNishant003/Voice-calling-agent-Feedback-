"""Real Postgres + the actual FastAPI app for all seven `/api/v1/demo/playground/steps/*` routes
(docs/11_BUILD_PLAN.md's Demo MVP section). The demo-mode-off 404 check for these routes lives in
`test_demo_api.py`'s `_DEMO_ROUTES` list (extended there) — this file is the happy/error paths.

Unlike the live call, the Playground never retries or falls back on a bad LLM response — a
malformed result should surface as a clean error, not be papered over, since papering over the
exact thing someone is testing for would defeat the tool's purpose. That's asserted explicitly here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.interfaces import LLMResult


def _llm_result(data: dict[str, object]) -> LLMResult:
    return LLMResult(
        data=data, raw_text=str(data), input_tokens=5, output_tokens=2, model="fake", latency_ms=9
    )


@pytest_asyncio.fixture
async def configured_app(configured_db_env: None) -> AsyncIterator[FastAPI]:
    del configured_db_env
    from app.main import app as fastapi_app

    yield fastapi_app


@pytest_asyncio.fixture
async def client(configured_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=configured_app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as ac:
        yield ac


async def _save_connected_gemini_key(client: AsyncClient) -> None:
    with patch.dict("app.api.v1.demo._TEST_FNS", {"gemini": AsyncMock(return_value=None)}):
        response = await client.post(
            "/api/v1/demo/providers/gemini/key",
            json={"api_key": "fake-key", "model": "gemini-3.8-flash"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


async def test_language_detection_happy_path(client: AsyncClient, demo_mode_on: None) -> None:
    del demo_mode_on
    await _save_connected_gemini_key(client)
    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(
            return_value=_llm_result({"detected_language": "hi", "requested_language": None})
        ),
    ):
        response = await client.post(
            "/api/v1/demo/playground/steps/language-detection",
            json={"provider": "gemini", "model": "gemini-3.8-flash", "patient_text": "theek tha"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["detected_language"] == "hi"
    assert body["latency_ms"] == 9
    assert body["input_tokens"] == 5


async def test_topic_extraction_happy_path(client: AsyncClient, demo_mode_on: None) -> None:
    del demo_mode_on
    await _save_connected_gemini_key(client)
    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(return_value=_llm_result({"topics": ["doctor", "billing"]})),
    ):
        response = await client.post(
            "/api/v1/demo/playground/steps/topic-extraction",
            json={
                "provider": "gemini",
                "model": "gemini-3.8-flash",
                "patient_text": "Doctor achhe the, billing confusing thi",
            },
        )
    assert response.status_code == 200
    assert response.json()["topics"] == ["doctor", "billing"]


async def test_llm_step_with_unconfigured_provider_returns_422(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    response = await client.post(
        "/api/v1/demo/playground/steps/language-detection",
        json={"provider": "openai", "model": "gpt-6-sol", "patient_text": "hello"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PFA-DEMO-008"


async def test_llm_step_malformed_output_is_a_clean_error_not_a_silent_fallback(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    await _save_connected_gemini_key(client)
    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(
            return_value=_llm_result({"detected_language": "not-a-real-language"})
        ),
    ):
        response = await client.post(
            "/api/v1/demo/playground/steps/language-detection",
            json={"provider": "gemini", "model": "gemini-3.8-flash", "patient_text": "hello"},
        )
    # Unlike the live call, no retry-then-fallback: this must surface as a clear error.
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "PFA-DEMO-004"


async def test_language_lock_and_topic_tracking_need_no_provider_at_all(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    # Deliberately no provider key saved anywhere in this test — these two steps are pure.
    lock = await client.post(
        "/api/v1/demo/playground/steps/language-lock",
        json={
            "detected_language": "en",
            "requested_language": "hi",
            "prior_locked_language": "english",
            "prior_streak": 0,
        },
    )
    assert lock.status_code == 200
    assert lock.json() == {
        "locked_language": "hindi_hinglish",
        "consecutive_other_count": 0,
        "switched": True,
    }

    tracking = await client.post(
        "/api/v1/demo/playground/steps/topic-tracking",
        json={"topics_mentioned": ["billing"], "prior_topics_covered": ["doctor"]},
    )
    assert tracking.status_code == 200
    assert tracking.json() == {"topics_covered": ["billing", "doctor"]}


async def test_end_judgment_and_end_ceiling(client: AsyncClient, demo_mode_on: None) -> None:
    del demo_mode_on
    await _save_connected_gemini_key(client)
    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(
            return_value=_llm_result({"wants_to_end": True, "summary": "All covered."})
        ),
    ):
        judgment = await client.post(
            "/api/v1/demo/playground/steps/end-judgment",
            json={
                "provider": "gemini",
                "model": "gemini-3.8-flash",
                "patient_text": "Bas itna hi",
                "topics_covered": ["doctor", "staff"],
                "turn_count": 4,
            },
        )
    assert judgment.status_code == 200
    assert judgment.json()["wants_to_end"] is True

    # The ceiling is pure and needs no model — forces an end at MAX_TURNS regardless of the signal.
    ceiling = await client.post(
        "/api/v1/demo/playground/steps/end-ceiling",
        json={"turn_count": 8, "llm_wants_to_end": False},
    )
    assert ceiling.status_code == 200
    assert ceiling.json() == {"ends": True}


async def test_response_generation_uses_saved_demo_settings(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    await _save_connected_gemini_key(client)
    await client.put(
        "/api/v1/demo/settings",
        json={
            "hospital_name": "Playground Test Hospital",
            "agent_name": "Meera",
            "voice_gender": "female",
        },
    )

    mock_complete = AsyncMock(
        return_value=_llm_result({"response": "Dhanyavaad!", "next_action": "close"})
    )
    with patch("app.adapters.gemini.llm.GeminiLLM.complete", new=mock_complete):
        response = await client.post(
            "/api/v1/demo/playground/steps/response-generation",
            json={
                "provider": "gemini",
                "model": "gemini-3.8-flash",
                "patient_text": "Sab badhiya tha",
                "locked_language": "hindi_hinglish",
                "topics_covered": ["doctor"],
                "is_ending": True,
            },
        )
    assert response.status_code == 200
    assert response.json()["response"] == "Dhanyavaad!"

    system_instruction = mock_complete.call_args.args[1]["system_instruction"]
    assert "Playground Test Hospital" in system_instruction
    assert "Meera" in system_instruction
