"""Real Postgres: `auth_service.login`/`refresh`/`logout` (docs/04_API_SPEC.md §2,
docs/06_ERROR_HANDLING_AND_MESSAGES.md PFA-AUTH-00x, docs/07_SECURITY_AND_COMPLIANCE.md §2).

All three take a `superadmin_session` — see that module's docstring for why (identity isn't known
yet, so RLS on `users`/`refresh_tokens` would hide the very row being looked up).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError
from app.core.security import get_jwt_keys, hash_password, hash_refresh_token, verify_access_token
from app.db.models.auth import RefreshToken
from app.db.models.compliance import AuditLogEntry
from app.db.models.tenancy import Account, User
from app.domain.enums import UserRole
from app.services import auth_service
from app.services.auth_service import LOCKOUT_THRESHOLD

_PASSWORD = "correct horse battery staple"


def _account(**overrides: object) -> Account:
    defaults: dict[str, object] = {
        "name": "Auth Test Hospital",
        "display_name_tts": "Auth Test Hospital",
        "caller_id_e164": "+911234567890",
        "retention_policy": {"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        "sla_config": {"p1": {"ack": 1, "resolve": 24}},
    }
    defaults.update(overrides)
    return Account(**defaults)


def _user(account_id: UUID | None, email: str, **overrides: object) -> User:
    defaults: dict[str, object] = {
        "account_id": account_id,
        "email": email,
        "name": "Test User",
        "role": UserRole.quality,
        "password_hash": hash_password(_PASSWORD),
    }
    defaults.update(overrides)
    return User(**defaults)


@pytest.fixture
async def account_and_user(superadmin_session: AsyncSession) -> dict[str, object]:
    account = _account()
    superadmin_session.add(account)
    await superadmin_session.commit()

    # Tests here don't run inside a rolled-back transaction (each commits for real against the
    # shared session-scoped container), so a fixed email would collide with `users_email_key`
    # the second time this fixture runs — unique per invocation via the account's own id instead.
    user = _user(account.account_id, f"login-test-{account.account_id}@example.com")
    superadmin_session.add(user)
    await superadmin_session.commit()

    return {"account": account, "user": user}


@pytest.mark.asyncio
async def test_successful_login_issues_tokens_audits_and_updates_last_login(
    superadmin_session: AsyncSession, account_and_user: dict[str, object]
) -> None:
    account: Account = account_and_user["account"]  # type: ignore[assignment]
    user: User = account_and_user["user"]  # type: ignore[assignment]

    async with superadmin_session.begin():
        result = await auth_service.login(superadmin_session, user.email, _PASSWORD)

    assert result.user.user_id == user.user_id
    assert result.access_token
    assert result.refresh_token

    # The access token verifies and carries the right claims.
    _private_key, public_key, kid = get_jwt_keys()
    claims = verify_access_token(result.access_token, {kid: public_key})
    assert claims.user_id == str(user.user_id)
    assert claims.account_id == str(account.account_id)
    assert claims.role == UserRole.quality

    await superadmin_session.refresh(user)
    assert user.last_login_at is not None
    assert user.failed_logins == 0
    assert user.locked_until is None

    refresh_rows = list(
        (
            await superadmin_session.scalars(
                select(RefreshToken).where(RefreshToken.user_id == user.user_id)
            )
        ).all()
    )
    assert len(refresh_rows) == 1
    assert refresh_rows[0].revoked_at is None

    audit_rows = list(
        (
            await superadmin_session.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "login.success",
                    AuditLogEntry.entity_id == user.user_id,
                )
            )
        ).all()
    )
    assert len(audit_rows) == 1


@pytest.mark.asyncio
async def test_five_failed_logins_locks_account_and_sixth_rejected_without_password_check(
    superadmin_session: AsyncSession, account_and_user: dict[str, object]
) -> None:
    user: User = account_and_user["user"]  # type: ignore[assignment]

    for _ in range(LOCKOUT_THRESHOLD):
        async with superadmin_session.begin():
            with pytest.raises(AuthError) as exc_info:
                await auth_service.login(superadmin_session, user.email, "wrong-password")
        assert exc_info.value.code == "PFA-AUTH-001"

    # A bare read autobegins its own transaction on this session (SQLAlchemy 2.0 "autobegin") and
    # leaves it open — an explicit `async with session.begin()` right after would then hit "a
    # transaction is already begun", so every step on this shared session gets its own block.
    async with superadmin_session.begin():
        await superadmin_session.refresh(user)
    assert user.failed_logins == LOCKOUT_THRESHOLD
    assert user.locked_until is not None

    # 6th attempt uses the *correct* password — still rejected, and as a lockout (not a password
    # failure), proving the lockout check short-circuits before `verify_password` runs.
    async with superadmin_session.begin():
        with pytest.raises(AuthError) as exc_info:
            await auth_service.login(superadmin_session, user.email, _PASSWORD)
    assert exc_info.value.code == "PFA-AUTH-003"

    async with superadmin_session.begin():
        await superadmin_session.refresh(user)
    # Unchanged — the 6th attempt never reached `verify_password`.
    assert user.failed_logins == LOCKOUT_THRESHOLD

    failure_audit_rows = list(
        (
            await superadmin_session.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "login.failure",
                    AuditLogEntry.entity_id == user.user_id,
                )
            )
        ).all()
    )
    # The lockout rejection itself (the 6th attempt) isn't audited.
    assert len(failure_audit_rows) == LOCKOUT_THRESHOLD


@pytest.mark.asyncio
async def test_refresh_rotates_token_in_same_family(
    superadmin_session: AsyncSession, account_and_user: dict[str, object]
) -> None:
    user: User = account_and_user["user"]  # type: ignore[assignment]

    async with superadmin_session.begin():
        login_result = await auth_service.login(superadmin_session, user.email, _PASSWORD)

    async with superadmin_session.begin():
        refreshed = await auth_service.refresh(superadmin_session, login_result.refresh_token)

    # `refresh_token` is always a fresh random opaque value. `access_token` is not asserted
    # different here: EdDSA signing is deterministic, and `issue_access_token` truncates `iat`/
    # `exp` to whole seconds, so two calls with identical claims within the same wall-clock second
    # produce byte-identical JWTs — that's expected, not a bug.
    assert refreshed.refresh_token != login_result.refresh_token

    rows_by_hash = {
        row.token_hash: row
        for row in (
            await superadmin_session.scalars(
                select(RefreshToken).where(RefreshToken.user_id == user.user_id)
            )
        ).all()
    }
    assert len(rows_by_hash) == 2

    old_row = rows_by_hash[hash_refresh_token(login_result.refresh_token)]
    new_row = rows_by_hash[hash_refresh_token(refreshed.refresh_token)]

    assert old_row.revoked_at is not None
    assert old_row.replaced_by == new_row.token_id
    assert new_row.revoked_at is None
    assert new_row.family_id == old_row.family_id


@pytest.mark.asyncio
async def test_reused_revoked_refresh_token_revokes_whole_family(
    superadmin_session: AsyncSession, account_and_user: dict[str, object]
) -> None:
    user: User = account_and_user["user"]  # type: ignore[assignment]

    async with superadmin_session.begin():
        login_result = await auth_service.login(superadmin_session, user.email, _PASSWORD)
    original_refresh_token = login_result.refresh_token

    async with superadmin_session.begin():
        rotated = await auth_service.refresh(superadmin_session, original_refresh_token)
    legitimate_next_token = rotated.refresh_token

    # Reuse of the now-revoked original token: the whole family (including the legitimate token
    # issued by the rotation above) gets revoked, not just the presented one.
    async with superadmin_session.begin():
        with pytest.raises(AuthError) as exc_info:
            await auth_service.refresh(superadmin_session, original_refresh_token)
    assert exc_info.value.code == "PFA-AUTH-002"

    async with superadmin_session.begin():
        reuse_audit_rows = list(
            (
                await superadmin_session.scalars(
                    select(AuditLogEntry).where(
                        AuditLogEntry.action == "auth.refresh_reuse_detected",
                        AuditLogEntry.actor_id == user.user_id,
                    )
                )
            ).all()
        )
    assert len(reuse_audit_rows) == 1

    # The legitimate token from the one valid rotation is now also revoked as collateral.
    async with superadmin_session.begin():
        with pytest.raises(AuthError) as exc_info:
            await auth_service.refresh(superadmin_session, legitimate_next_token)
    assert exc_info.value.code == "PFA-AUTH-002"


@pytest.mark.asyncio
async def test_logout_revokes_family_and_is_idempotent(
    superadmin_session: AsyncSession, account_and_user: dict[str, object]
) -> None:
    user: User = account_and_user["user"]  # type: ignore[assignment]

    async with superadmin_session.begin():
        login_result = await auth_service.login(superadmin_session, user.email, _PASSWORD)

    async with superadmin_session.begin():
        await auth_service.logout(superadmin_session, login_result.refresh_token)

    async with superadmin_session.begin():
        with pytest.raises(AuthError) as exc_info:
            await auth_service.refresh(superadmin_session, login_result.refresh_token)
    assert exc_info.value.code == "PFA-AUTH-002"

    # Idempotent: logging out again with the same (already-revoked) token doesn't raise.
    async with superadmin_session.begin():
        await auth_service.logout(superadmin_session, login_result.refresh_token)
