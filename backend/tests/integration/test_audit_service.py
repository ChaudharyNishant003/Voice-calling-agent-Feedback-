"""Real Postgres: sequential and concurrent `audit_service.record()` calls produce a valid,
unbroken chain (docs/07_SECURITY_AND_COMPLIANCE.md §6) — proves the advisory lock actually
serializes concurrent writers rather than just looking correct in isolation.

Writes go through `app_session` (pfa_app — the normal app role, which has INSERT on audit_log).
Reads go through `superadmin_session` (pfa_superadmin) since pfa_app is INSERT-only there
(doc 02 §3) — see migration 0011.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models.compliance import AuditLogEntry
from app.domain.audit_chain import verify_chain
from app.services import audit_service


@pytest.mark.asyncio
async def test_sequential_records_form_a_valid_chain(
    app_session: AsyncSession, superadmin_session: AsyncSession
) -> None:
    async with app_session.begin():
        for i in range(5):
            await audit_service.record(
                app_session,
                account_id=None,
                actor_type="system",
                actor_id=None,
                action=f"test.sequential.{i}",
                entity_type="test",
                entity_id=None,
            )

    rows = list(
        (
            await superadmin_session.scalars(select(AuditLogEntry).order_by(AuditLogEntry.log_id))
        ).all()
    )
    assert len(rows) >= 5
    assert verify_chain(rows) == []


@pytest.mark.asyncio
async def test_concurrent_records_still_form_a_valid_chain(
    migrated_database: dict[str, str],
) -> None:
    app_engine = create_async_engine(migrated_database["app"])
    app_maker = async_sessionmaker(app_engine, expire_on_commit=False)

    async def _write_one(i: int) -> None:
        async with app_maker() as session, session.begin():
            await audit_service.record(
                session,
                account_id=None,
                actor_type="system",
                actor_id=None,
                action=f"test.concurrent.{i}",
                entity_type="test",
                entity_id=None,
            )

    await asyncio.gather(*(_write_one(i) for i in range(10)))
    await app_engine.dispose()

    superadmin_engine = create_async_engine(migrated_database["superadmin"])
    try:
        async with async_sessionmaker(superadmin_engine, expire_on_commit=False)() as session:
            rows = list(
                (await session.scalars(select(AuditLogEntry).order_by(AuditLogEntry.log_id))).all()
            )
            recent = [r for r in rows if r.action.startswith("test.concurrent.")]
            assert len(recent) == 10
            assert verify_chain(rows) == []  # whole-table chain, not just `recent`
    finally:
        await superadmin_engine.dispose()
