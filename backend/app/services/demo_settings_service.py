"""Demo MVP hospital/agent name + voice gender settings (spec §14) — a single fixed-id row."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.demo import DemoSettings

_SINGLETON_ID = 1


async def get_settings(session: AsyncSession) -> DemoSettings:
    row = await session.get(DemoSettings, _SINGLETON_ID)
    if row is None:
        # Migration 0015 seeds this row, but tests build a fresh schema without running the data
        # seed — same "insert if missing" safety net as any other singleton-config read.
        row = DemoSettings(id=_SINGLETON_ID)
        session.add(row)
        await session.flush()
    return row


async def save_settings(
    session: AsyncSession, *, hospital_name: str, agent_name: str, voice_gender: str
) -> DemoSettings:
    row = await get_settings(session)
    row.hospital_name = hospital_name
    row.agent_name = agent_name
    row.voice_gender = voice_gender
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row
