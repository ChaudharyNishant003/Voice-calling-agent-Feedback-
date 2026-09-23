"""Declarative base + async engine/session factory (docs/01_ARCHITECTURE.md §3).

The app connects as the restricted `pfa_app` role (see `core/config.py`), not the migration
superuser, so Postgres RLS (doc 02 §5) is actually enforced rather than bypassed by ownership.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    # doc 02: "All timestamps timestamptz in UTC" — every bare `Mapped[datetime]` column gets
    # `TIMESTAMP WITH TIME ZONE` from this map, so model columns always match what the migrations
    # actually create (they use `sa.TIMESTAMP(timezone=True)` explicitly) without repeating it
    # on every column.
    type_annotation_map = {datetime: DateTime(timezone=True)}


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
