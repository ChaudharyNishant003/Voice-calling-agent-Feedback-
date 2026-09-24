"""Auth endpoints (docs/04_API_SPEC.md §2). MFA (`mfa_required` branch, `/auth/mfa/verify`) and
password reset (`/auth/password/forgot|reset`) are Sprint 1 increment 3b — not built here.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CSRF_COOKIE,
    REFRESH_COOKIE,
    SESSION_COOKIE,
    generate_csrf_token,
    get_superadmin_db_session,
    verify_csrf,
)
from app.core.errors import AuthError
from app.core.ids import format_id
from app.core.security import ACCESS_TOKEN_TTL_S
from app.services import auth_service
from app.services.auth_service import LoginResult

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_MAX_AGE_S = int(timedelta(hours=12).total_seconds())


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    user_id: str
    role: str
    account_id: str | None


def _login_response(result: LoginResult) -> LoginResponse:
    return LoginResponse(
        user_id=format_id("user", result.user.user_id),
        role=result.user.role.value,
        account_id=format_id("account", result.user.account_id) if result.user.account_id else None,
    )


def _set_session_cookies(response: Response, result: LoginResult) -> None:
    # __Host- prefix *requires* Secure, Path=/ exactly, and no Domain attribute — compliant clients
    # (curl, every major browser) silently refuse to even store a `__Host-`-named cookie that
    # doesn't satisfy this, which an earlier version of this code violated by scoping the refresh
    # cookie to Path=/api/v1/auth: caught by manually driving `/auth/login` -> `/auth/refresh`
    # through curl against the real running API (httpx's test client doesn't enforce the `__Host-`
    # prefix rule, so the integration tests passed while the cookie was silently never being set in
    # any real client). Both session and refresh cookies keep the `__Host-` prefix's stronger
    # guarantees at the cost of the refresh token being sent on every path, not just /auth/*.
    response.set_cookie(
        SESSION_COOKIE,
        result.access_token,
        max_age=ACCESS_TOKEN_TTL_S,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        result.refresh_token,
        max_age=_REFRESH_COOKIE_MAX_AGE_S,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    # Double-submit CSRF token: deliberately *not* HttpOnly, so client-side JS can read it and echo
    # it back as the X-CSRF-Token header (doc 04 §1).
    response.set_cookie(
        CSRF_COOKIE,
        generate_csrf_token(),
        max_age=_REFRESH_COOKIE_MAX_AGE_S,
        httponly=False,
        secure=True,
        samesite="strict",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> LoginResponse:
    result = await auth_service.login(session, body.email, body.password)
    _set_session_cookies(response, result)
    return _login_response(result)


@router.post("/refresh", dependencies=[Depends(verify_csrf)])
async def refresh_session(
    response: Response,
    session: AsyncSession = Depends(get_superadmin_db_session),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> LoginResponse:
    if refresh_token is None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")
    result = await auth_service.refresh(session, refresh_token)
    _set_session_cookies(response, result)
    return _login_response(result)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(
    response: Response,
    session: AsyncSession = Depends(get_superadmin_db_session),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> dict[str, str]:
    if refresh_token is not None:
        await auth_service.logout(session, refresh_token)
    _clear_session_cookies(response)
    return {"status": "ok"}
