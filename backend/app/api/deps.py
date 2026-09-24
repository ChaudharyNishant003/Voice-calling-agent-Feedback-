"""Shared FastAPI dependencies (docs/04_API_SPEC.md §1-2, docs/07_SECURITY_AND_COMPLIANCE.md §1).

Cookie names: doc 04 §1 names one session cookie (`__Host-pfa_session`) as holding "a short-lived
JWT + rotating refresh token" — ambiguous about whether that's one cookie or two. This uses two,
since the access and refresh tokens have different lifetimes (15 min vs 8h/12h) — the more common
and more secure pattern, and not a compliance/safety call, just an implementation detail the doc
left open. Both are `Path=/` (not `/auth`-only for the refresh cookie): the `__Host-` prefix on
either name *requires* `Path=/` exactly, or compliant clients refuse to store the cookie at all —
see `api/v1/auth.py`'s `_set_session_cookies` for how that was caught.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, PermissionError_
from app.core.security import Permission, has_permission
from app.db.base import get_session, get_superadmin_session
from app.db.models.tenancy import User
from app.services import auth_service

SESSION_COOKIE = "__Host-pfa_session"
REFRESH_COOKIE = "__Host-pfa_refresh"
CSRF_COOKIE = "pfa_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped `pfa_app` session: commits at the end of a successful request, rolls back on
    any exception (the request's whole handler runs in one transaction).
    """
    async for session in get_session():
        async with session.begin():
            yield session


async def get_superadmin_db_session() -> AsyncIterator[AsyncSession]:
    """Request-scoped `pfa_superadmin` session — only for the auth endpoints
    (`login`/`refresh`/`logout`) that structurally need it; see `services/auth_service.py`'s module
    docstring for why.
    """
    async for session in get_superadmin_session():
        async with session.begin():
            yield session


async def get_current_user(
    session: AsyncSession = Depends(get_db_session),
    access_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if access_token is None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")
    return await auth_service.resolve_current_user(session, access_token)


def require(permission: Permission):  # type: ignore[no-untyped-def]
    async def _check(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise PermissionError_(
                "PFA-USR-001",
                message="You don't have access to this action. Ask your administrator.",
            )
        return user

    # Marker for tests/unit/test_route_completeness.py — a plain closure has no way to identify
    # itself as "a require() dependency" otherwise, since FastAPI's dependant tree only stores the
    # callable, not why it was added.
    _check.__pfa_permission__ = permission  # type: ignore[attr-defined]
    return _check


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


async def verify_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
) -> None:
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
        raise AuthError(
            "PFA-AUTH-005", message="Your session needs refreshing. Please reload the page."
        )
