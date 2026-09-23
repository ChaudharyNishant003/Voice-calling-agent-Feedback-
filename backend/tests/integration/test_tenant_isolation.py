"""RLS actually isolates tenants (docs/02_DATA_MODEL.md §5, doc 08 §7 tenant-isolation suite).

Account provisioning itself runs as `pfa_superadmin` (BYPASSRLS) — a brand-new account has no
"current scope" yet for `pfa_app`'s WITH CHECK policy to match, so tenant creation is inherently a
platform-level operation, not a tenant-scoped one. `locations` is used as the isolation subject
since it has the smallest FK graph of any tenant table (just `account_id`).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenancy import Account, Location
from app.db.session import set_account_scope


def _account(**overrides: object) -> Account:
    defaults: dict[str, object] = {
        "name": "Test Hospital",
        "display_name_tts": "Test Hospital",
        "caller_id_e164": "+911234567890",
        "retention_policy": {"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        "sla_config": {"p1": {"ack": 1, "resolve": 24}},
    }
    defaults.update(overrides)
    return Account(**defaults)


@pytest.mark.asyncio
async def test_pfa_app_cannot_see_another_tenants_rows(
    app_session: AsyncSession, superadmin_session: AsyncSession
) -> None:
    account_a, account_b = _account(), _account()
    superadmin_session.add_all([account_a, account_b])
    await superadmin_session.commit()

    superadmin_session.add_all(
        [
            Location(
                account_id=account_a.account_id, external_location_id="loc-a", name="Location A"
            ),
            Location(
                account_id=account_b.account_id, external_location_id="loc-b", name="Location B"
            ),
        ]
    )
    await superadmin_session.commit()

    await app_session.begin()
    await set_account_scope(app_session, account_a.account_id)
    visible = (await app_session.scalars(select(Location))).all()
    await app_session.rollback()

    assert [loc.external_location_id for loc in visible] == ["loc-a"]


@pytest.mark.asyncio
async def test_pfa_app_cannot_insert_under_another_accounts_id(
    app_session: AsyncSession, superadmin_session: AsyncSession
) -> None:
    account_a, account_b = _account(), _account()
    superadmin_session.add_all([account_a, account_b])
    await superadmin_session.commit()

    await app_session.begin()
    await set_account_scope(app_session, account_a.account_id)
    app_session.add(
        Location(account_id=account_b.account_id, external_location_id="sneaky", name="Sneaky")
    )

    with pytest.raises(DBAPIError, match="row-level security"):
        await app_session.commit()
    await app_session.rollback()


@pytest.mark.asyncio
async def test_superadmin_bypasses_rls(
    app_session: AsyncSession, superadmin_session: AsyncSession
) -> None:
    account_a = _account()
    superadmin_session.add(account_a)
    await superadmin_session.commit()
    superadmin_session.add(
        Location(account_id=account_a.account_id, external_location_id="loc-a", name="Location A")
    )
    await superadmin_session.commit()

    other_account = _account()
    superadmin_session.add(other_account)
    await superadmin_session.commit()

    await app_session.begin()
    await set_account_scope(app_session, other_account.account_id)
    visible_to_scoped_app: list[UUID] = [
        loc.location_id for loc in (await app_session.scalars(select(Location))).all()
    ]
    await app_session.rollback()
    assert visible_to_scoped_app == []

    visible_to_superadmin = (await superadmin_session.scalars(select(Location))).all()
    assert account_a.account_id in {loc.account_id for loc in visible_to_superadmin}
