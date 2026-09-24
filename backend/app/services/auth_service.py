"""Auth I/O layer (docs/04_API_SPEC.md §2, docs/07_SECURITY_AND_COMPLIANCE.md §2). All the crypto
primitives (`hash_password`, `issue_access_token`, ...) live in `core/security.py`; this module
does the DB reads/writes and lockout/rotation policy around them.

`login()` and `refresh()` take a `superadmin_session` (BYPASSRLS), not the regular tenant-scoped
`pfa_app` session — deliberately, not an oversight. Both look a row up by something that doesn't
carry a legible tenant (an email address; an opaque refresh-token hash), so there's no `account_id`
yet to scope a regular session by — RLS on `users`/`refresh_tokens` would hide the very row being
looked up. Once identity *is* established (from here on: `get_current_user` for a regular tenant
user, or any code after `login`/`refresh` returns), the account_id is known and RLS applies
normally via a properly-scoped session for the rest of the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError
from app.core.ids import uuid7
from app.core.security import (
    generate_refresh_token,
    get_jwt_keys,
    hash_refresh_token,
    issue_access_token,
    verify_access_token,
    verify_password,
)
from app.db.base import get_superadmin_sessionmaker
from app.db.models.auth import RefreshToken
from app.db.models.tenancy import User
from app.db.session import set_account_scope
from app.services import audit_service

LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)
REFRESH_IDLE_TTL = timedelta(hours=8)
REFRESH_ABSOLUTE_TTL = timedelta(hours=12)


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    user: User


def _jwt_context() -> tuple[object, str]:
    private_key, _public_key, kid = get_jwt_keys()
    return private_key, kid


async def _issue_session(
    superadmin_session: AsyncSession, user: User, *, now: datetime
) -> LoginResult:
    private_key, kid = _jwt_context()
    access_token = issue_access_token(
        user_id=str(user.user_id),
        account_id=str(user.account_id) if user.account_id else None,
        role=user.role,
        private_key=private_key,  # type: ignore[arg-type]
        kid=kid,
        now=now.timestamp(),
    )
    refresh_token = generate_refresh_token()
    superadmin_session.add(
        RefreshToken(
            user_id=user.user_id,
            family_id=uuid7(),
            token_hash=hash_refresh_token(refresh_token),
            expires_at=now + REFRESH_IDLE_TTL,
        )
    )
    await superadmin_session.flush()
    return LoginResult(access_token=access_token, refresh_token=refresh_token, user=user)


async def login(
    superadmin_session: AsyncSession, email: str, password: str, *, now: datetime | None = None
) -> LoginResult:
    now = now or datetime.now(UTC)
    user = await superadmin_session.scalar(select(User).where(User.email == email))

    if user is None or user.password_hash is None:
        # Same error regardless of whether the email exists (doc 06 PFA-AUTH-001) — no enumeration.
        raise AuthError("PFA-AUTH-001", message="Email or password is incorrect.")

    if user.locked_until is not None and user.locked_until > now:
        raise AuthError("PFA-AUTH-003", message="Too many attempts. Try again in 15 minutes.")

    if not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= LOCKOUT_THRESHOLD:
            user.locked_until = now + LOCKOUT_DURATION
        await superadmin_session.flush()
        await audit_service.record(
            superadmin_session,
            account_id=user.account_id,
            actor_type="user",
            actor_id=user.user_id,
            action="login.failure",
            entity_type="user",
            entity_id=user.user_id,
        )
        raise AuthError("PFA-AUTH-001", message="Email or password is incorrect.")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    await superadmin_session.flush()

    result = await _issue_session(superadmin_session, user, now=now)

    await audit_service.record(
        superadmin_session,
        account_id=user.account_id,
        actor_type="user",
        actor_id=user.user_id,
        action="login.success",
        entity_type="user",
        entity_id=user.user_id,
    )
    return result


async def refresh(
    superadmin_session: AsyncSession, refresh_token: str, *, now: datetime | None = None
) -> LoginResult:
    now = now or datetime.now(UTC)
    token_hash = hash_refresh_token(refresh_token)
    row = await superadmin_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )

    if row is None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    if row.revoked_at is not None:
        # Reuse of an already-rotated-away token: the whole family is compromised (doc 07 §2's
        # "reuse -> revoke family, alert" — alert routing is a later observability-sprint concern).
        await superadmin_session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await audit_service.record(
            superadmin_session,
            account_id=None,
            actor_type="system",
            actor_id=row.user_id,
            action="auth.refresh_reuse_detected",
            entity_type="refresh_token_family",
            entity_id=row.family_id,
        )
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    if row.expires_at <= now:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    family_rows = (
        await superadmin_session.scalars(
            select(RefreshToken.created_at)
            .where(RefreshToken.family_id == row.family_id)
            .order_by(RefreshToken.created_at.asc())
            .limit(1)
        )
    ).first()
    if family_rows is not None and now - family_rows > REFRESH_ABSOLUTE_TTL:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    user = await superadmin_session.get(User, row.user_id)
    if user is None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    private_key, kid = _jwt_context()
    access_token = issue_access_token(
        user_id=str(user.user_id),
        account_id=str(user.account_id) if user.account_id else None,
        role=user.role,
        private_key=private_key,  # type: ignore[arg-type]
        kid=kid,
        now=now.timestamp(),
    )
    new_refresh_token = generate_refresh_token()
    new_row = RefreshToken(
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=hash_refresh_token(new_refresh_token),
        expires_at=now + REFRESH_IDLE_TTL,
    )
    superadmin_session.add(new_row)
    await superadmin_session.flush()

    row.revoked_at = now
    row.replaced_by = new_row.token_id
    await superadmin_session.flush()

    return LoginResult(access_token=access_token, refresh_token=new_refresh_token, user=user)


async def logout(
    superadmin_session: AsyncSession, refresh_token: str, *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    token_hash = hash_refresh_token(refresh_token)
    row = await superadmin_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if row is None:
        return  # already gone — logout is idempotent
    await superadmin_session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def get_current_user(session: AsyncSession, access_token: str) -> User:
    """For a regular tenant user (the common case). Sets `session`'s RLS scope from the token's
    (signed, tamper-proof) `account_id` claim, then looks the user up through it — this is the one
    lookup in this module that *can* go through a regular tenant-scoped session, since the account
    is already known from the token rather than needing to be discovered by the query itself.

    Raises if the token claims `account_id is None` (a super_admin token) — callers must route
    those through `get_current_super_admin` instead; see that function's docstring for why a
    regular session structurally cannot resolve that case.
    """
    _private_key, public_key, kid = get_jwt_keys()
    claims = verify_access_token(access_token, {kid: public_key})

    if claims.account_id is None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    await set_account_scope(session, UUID(claims.account_id))
    user = await session.get(User, UUID(claims.user_id))

    if user is None or not user.is_active:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")
    return user


async def resolve_current_user(session: AsyncSession, access_token: str) -> User:
    """Single entry point for `api/deps.py` — decodes the token once and routes to
    `get_current_user` (regular tenant user, using `session`) or `get_current_super_admin` (opens
    its own short-lived superadmin session) so the FastAPI layer doesn't need to know this
    branching exists at all.
    """
    _private_key, public_key, kid = get_jwt_keys()
    claims = verify_access_token(access_token, {kid: public_key})

    if claims.account_id is None:
        return await get_current_super_admin(access_token)
    return await get_current_user(session, access_token)


async def get_current_super_admin(access_token: str) -> User:
    """`users` RLS has no "or account_id IS NULL" escape (unlike suppression_list/audit_log) —
    resolving a super_admin's own identity (account_id NULL) genuinely needs BYPASSRLS access.
    Opens its own short-lived superadmin session rather than requiring the caller to provide one on
    every request (`api/deps.py`'s `get_current_user` dependency only reaches this path for the
    rare super_admin token, decided from the token's claims before any DB session is opened).
    """
    _private_key, public_key, kid = get_jwt_keys()
    claims = verify_access_token(access_token, {kid: public_key})
    if claims.account_id is not None:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")

    async with get_superadmin_sessionmaker()() as superadmin_session:
        user = await superadmin_session.get(User, UUID(claims.user_id))

    if user is None or not user.is_active:
        raise AuthError("PFA-AUTH-002", message="Your session has expired. Please sign in again.")
    return user
