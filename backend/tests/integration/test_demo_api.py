"""Real Postgres + the actual FastAPI app, through `httpx.AsyncClient` (Demo MVP spec §22-23):
every `/api/v1/demo/*` route 404s while `DEMO_MODE` is off; with it on, the full happy path works
end to end, an unconfigured provider fails cleanly (not a crash), and malformed LLM output recovers
via the fallback response rather than surfacing a 500.

Real vendor calls are never made here: `_TEST_FNS` (provider-key validation) and
`GeminiLLM.complete` (turn generation) are patched — this is an HTTP-contract test, not a
live-vendor test.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.interfaces import LLMResult
from app.core.config import get_settings
from app.core.errors import AdapterAuthError

_DEMO_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/demo/providers"),
    ("POST", "/api/v1/demo/providers/gemini/key"),
    ("GET", "/api/v1/demo/settings"),
    ("PUT", "/api/v1/demo/settings"),
    ("POST", "/api/v1/demo/calls"),
    ("POST", "/api/v1/demo/calls/00000000-0000-7000-8000-000000000000/turns"),
    ("POST", "/api/v1/demo/calls/00000000-0000-7000-8000-000000000000/end"),
    ("GET", "/api/v1/demo/calls/00000000-0000-7000-8000-000000000000/events"),
]

_GOOD_TURN_DATA = {
    "response": "Samajh gayi, dhanyavaad!",
    "detected_language": "hi",
    "topics": ["billing"],
    "next_action": "follow_up",
    "end_call": False,
}


def _llm_result(data: dict[str, object]) -> LLMResult:
    return LLMResult(
        data=data, raw_text=str(data), input_tokens=1, output_tokens=1, model="fake", latency_ms=1
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


@pytest.fixture
def demo_mode_on() -> AsyncIterator[None]:
    old = os.environ.get("DEMO_MODE")
    os.environ["DEMO_MODE"] = "true"
    get_settings.cache_clear()
    yield
    if old is None:
        os.environ.pop("DEMO_MODE", None)
    else:
        os.environ["DEMO_MODE"] = old
    get_settings.cache_clear()


async def test_every_demo_route_404s_when_demo_mode_off(client: AsyncClient) -> None:
    # DEMO_MODE defaults to False — no `demo_mode_on` fixture here.
    for method, path in _DEMO_ROUTES:
        body = {} if method in ("POST", "PUT") else None
        response = await client.request(method, path, json=body)
        assert response.status_code == 404, f"{method} {path} did not 404 with demo mode off"


async def test_save_provider_key_happy_and_invalid_paths(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    with patch.dict(
        "app.api.v1.demo._TEST_FNS", {"gemini": AsyncMock(return_value=None)}
    ):
        response = await client.post(
            "/api/v1/demo/providers/gemini/key",
            json={"api_key": "fake-key", "model": "gemini-3.8-flash"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "connected"

    with patch.dict(
        "app.api.v1.demo._TEST_FNS",
        {
            "gemini": AsyncMock(
                side_effect=AdapterAuthError("PFA-DEMO-002", message="rejected")
            )
        },
    ):
        response = await client.post(
            "/api/v1/demo/providers/gemini/key",
            json={"api_key": "bad-key", "model": "gemini-3.8-flash"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "invalid"


async def test_submit_turn_without_a_configured_provider_returns_422(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    start = await client.post("/api/v1/demo/calls", json={"provider": "gemini"})
    assert start.status_code == 200
    call_id = start.json()["call_id"]

    response = await client.post(
        f"/api/v1/demo/calls/{call_id}/turns", json={"provider": "gemini", "text": "hello"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PFA-DEMO-008"


async def test_full_call_happy_path_through_api(client: AsyncClient, demo_mode_on: None) -> None:
    del demo_mode_on
    with patch.dict("app.api.v1.demo._TEST_FNS", {"gemini": AsyncMock(return_value=None)}):
        await client.post(
            "/api/v1/demo/providers/gemini/key",
            json={"api_key": "fake-key", "model": "gemini-3.8-flash"},
        )

    start = await client.post("/api/v1/demo/calls", json={"provider": "gemini"})
    assert start.status_code == 200
    body = start.json()
    call_id = body["call_id"]
    assert body["greeting_text"]

    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(return_value=_llm_result(_GOOD_TURN_DATA)),
    ):
        turn = await client.post(
            f"/api/v1/demo/calls/{call_id}/turns",
            json={"provider": "gemini", "text": "Billing thodi confusing thi."},
        )
    assert turn.status_code == 200
    turn_body = turn.json()
    assert turn_body["response_text"] == _GOOD_TURN_DATA["response"]
    assert turn_body["topics"] == ["billing"]
    assert turn_body["end_call"] is False

    events = await client.get(f"/api/v1/demo/calls/{call_id}/events")
    assert events.status_code == 200
    event_types = [e["type"] for e in events.json()]
    assert "LLM_REQUEST" in event_types
    assert "LLM_RESPONSE" in event_types
    assert "ERROR" not in event_types

    end = await client.post(f"/api/v1/demo/calls/{call_id}/end")
    assert end.status_code == 200


async def test_malformed_llm_output_recovers_instead_of_crashing(
    client: AsyncClient, demo_mode_on: None
) -> None:
    del demo_mode_on
    with patch.dict("app.api.v1.demo._TEST_FNS", {"gemini": AsyncMock(return_value=None)}):
        await client.post(
            "/api/v1/demo/providers/gemini/key",
            json={"api_key": "fake-key", "model": "gemini-3.8-flash"},
        )
    start = await client.post("/api/v1/demo/calls", json={"provider": "gemini"})
    call_id = start.json()["call_id"]

    bad_result = _llm_result({"response": "bad", "detected_language": "not-a-real-language"})
    with patch(
        "app.adapters.gemini.llm.GeminiLLM.complete",
        new=AsyncMock(side_effect=[bad_result, bad_result]),
    ):
        turn = await client.post(
            f"/api/v1/demo/calls/{call_id}/turns",
            json={"provider": "gemini", "text": "Kuch samajh nahi aaya."},
        )
    assert turn.status_code == 200  # never a 500 — the call survives with a fallback response
    assert "samajh nahi aaya" in turn.json()["response_text"]

    events = await client.get(f"/api/v1/demo/calls/{call_id}/events")
    error_events = [e for e in events.json() if e["type"] == "ERROR"]
    assert len(error_events) == 3
