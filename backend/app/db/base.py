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


# `pfa_superadmin` (BYPASSRLS) — for the handful of operations that are structurally incapable of
# going through a tenant-scoped session: resolving a user's identity before their account_id is
# known (auth_service.login/refresh), a super_admin's own identity (no account_id to scope by),
# account provisioning, and whole-table reads like the nightly audit-chain verify. Never used for
# regular tenant-scoped request handling once identity is established.
@lru_cache
def get_superadmin_engine() -> AsyncEngine:
    return create_async_engine(get_settings().superadmin_database_url, pool_pre_ping=True)


@lru_cache
def get_superadmin_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_superadmin_engine(), expire_on_commit=False)


async def get_superadmin_session() -> AsyncIterator[AsyncSession]:
    async with get_superadmin_sessionmaker()() as session:
        yield session
