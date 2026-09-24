"""Real Postgres + the actual FastAPI app, through `httpx.AsyncClient` (docs/04_API_SPEC.md §2):
login sets all three cookies, `/me` works with the session cookie, refresh without the CSRF header
is rejected, logout revokes the session.

Cookies here are `Secure` (`__Host-` prefix requires it) — `http.cookiejar` (which httpx's cookie
jar wraps) only *sends back* `Secure` cookies on `https://` requests, so the client below uses
`base_url="https://testserver"`. `ASGITransport` never opens a real socket, so the scheme only
affects cookie-jar bookkeeping, not connectivity.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import format_id
from app.core.security import hash_password
from app.db.models.tenancy import Account, User
from app.domain.enums import UserRole

_PASSWORD = "correct horse battery staple"


async def _login(client: AsyncClient, user: User) -> None:
    await client.post("/api/v1/auth/login", json={"email": user.email, "password": _PASSWORD})


def _account() -> Account:
    return Account(
        name="Auth API Test Hospital",
        display_name_tts="Auth API Test Hospital",
        caller_id_e164="+911234567890",
        retention_policy={"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        sla_config={"p1": {"ack": 1, "resolve": 24}},
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
async def seeded_user(superadmin_session: AsyncSession) -> User:
    account = _account()
    superadmin_session.add(account)
    await superadmin_session.commit()

    # Not wrapped in a rolled-back transaction (see test_auth_service.py's fixture for why) — the
    # email must be unique per test run, not shared across the session-scoped container.
    user = User(
        account_id=account.account_id,
        email=f"api-test-{account.account_id}@example.com",
        name="API Test User",
        role=UserRole.quality,
        password_hash=hash_password(_PASSWORD),
    )
    superadmin_session.add(user)
    await superadmin_session.commit()
    return user


@pytest.mark.asyncio
async def test_login_sets_all_three_cookies(client: AsyncClient, seeded_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": seeded_user.email, "password": _PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == format_id("user", seeded_user.user_id)
    assert body["role"] == "quality"

    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(h.startswith("__Host-pfa_session=") for h in set_cookie_headers)
    assert any(h.startswith("__Host-pfa_refresh=") for h in set_cookie_headers)
    assert any(h.startswith("pfa_csrf=") for h in set_cookie_headers)

    # Regression guard: the `__Host-` prefix *requires* `Path=/` exactly (and Secure, and no
    # Domain) — a compliant client (every major browser, curl) silently refuses to store the
    # cookie at all otherwise. httpx's own cookie jar does *not* enforce this (an earlier version
    # of `_set_session_cookies` scoped the refresh cookie to `Path=/api/v1/auth`, which every test
    # here happily read back via `client.cookies[...]` — only driving a real login through curl
    # against the running API surfaced that the cookie was never actually being set). Parsed
    # directly off the raw header rather than `response.cookies`, since that's httpx's same lenient
    # parser.
    for header in set_cookie_headers:
        name = header.split("=", 1)[0]
        if name.startswith("__Host-"):
            attrs = {a.strip().lower() for a in header.split(";")[1:]}
            assert "path=/" in attrs, f"{name} must be Path=/ per __Host- rules: {header}"
            assert "secure" in attrs, f"{name} must be Secure per __Host- rules: {header}"


@pytest.mark.asyncio
async def test_me_works_with_session_cookie(client: AsyncClient, seeded_user: User) -> None:
    await _login(client, seeded_user)

    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == format_id("user", seeded_user.user_id)
    assert body["email"] == seeded_user.email
    assert "view_verbatim_transcript" in body["permissions"]


@pytest.mark.asyncio
async def test_refresh_without_csrf_header_is_rejected(
    client: AsyncClient, seeded_user: User
) -> None:
    await _login(client, seeded_user)

    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "PFA-AUTH-005"


@pytest.mark.asyncio
async def test_refresh_with_csrf_header_succeeds_and_rotates_refresh_cookie(
    client: AsyncClient, seeded_user: User
) -> None:
    await _login(client, seeded_user)
    old_refresh_cookie = client.cookies["__Host-pfa_refresh"]
    csrf_token = client.cookies["pfa_csrf"]

    response = await client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 200
    # The refresh token is always a fresh random value regardless of timing (unlike the access
    # JWT, whose claims — and so its signature, EdDSA being deterministic — could coincide with
    # the login response's if both happen within the same whole second).
    assert response.cookies["__Host-pfa_refresh"] != old_refresh_cookie


@pytest.mark.asyncio
async def test_logout_revokes_session_so_refresh_then_fails(
    client: AsyncClient, seeded_user: User
) -> None:
    await _login(client, seeded_user)
    csrf_token = client.cookies["pfa_csrf"]
    refresh_cookie = client.cookies["__Host-pfa_refresh"]
    headers = {"X-CSRF-Token": csrf_token}

    logout_response = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "ok"}

    # `logout` also clears the cookies client-side (Max-Age=0), so the client's jar no longer has
    # a `pfa_csrf`/`__Host-pfa_refresh` to send — a bare follow-up request would fail at the CSRF
    # check without ever reaching the revoked-token check this test cares about. Restoring the
    # pre-logout values on the client jar isolates that: the server rejects them because the token
    # itself is now revoked, not because the cookies are merely gone from the client.
    client.cookies.set("pfa_csrf", csrf_token)
    client.cookies.set("__Host-pfa_refresh", refresh_cookie)
    refresh_response = await client.post("/api/v1/auth/refresh", headers=headers)
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"]["code"] == "PFA-AUTH-002"
