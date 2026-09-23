"""Real-Postgres integration fixtures (docs/08_TESTING_STRATEGY.md §1 — testcontainers).

One container per test session: migrations run once (`upgrade head`), then each test gets its own
transaction via `db_session`/`db_session_as` so tests don't leak state into each other.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(
        "postgres:16", username="pfa", password="pfa", dbname="pfa"
    ) as container:
        yield container


@pytest.fixture(scope="session")
def superuser_url(postgres_container: PostgresContainer) -> str:
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    return f"postgresql+asyncpg://pfa:pfa@{host}:{port}/pfa"


@pytest.fixture(scope="session")
def migrated_database(superuser_url: str) -> Iterator[dict[str, str]]:
    """Run `upgrade head` once per session; returns the URLs each role should connect with."""
    old_env = {k: os.environ.get(k) for k in ("MIGRATION_DATABASE_URL", "DATABASE_URL")}
    os.environ["MIGRATION_DATABASE_URL"] = superuser_url
    get_settings.cache_clear()

    alembic_cfg = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", os.path.join(_BACKEND_ROOT, "app", "db", "alembic")
    )
    command.upgrade(alembic_cfg, "head")

    settings = get_settings()
    app_url = superuser_url.replace("pfa:pfa@", f"pfa_app:{settings.pfa_app_db_password}@")
    superadmin_url = superuser_url.replace(
        "pfa:pfa@", f"pfa_superadmin:{settings.pfa_superadmin_db_password}@"
    )

    try:
        yield {"superuser": superuser_url, "app": app_url, "superadmin": superadmin_url}
    finally:
        command.downgrade(alembic_cfg, "base")
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


async def _session_for(url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def app_session(migrated_database: dict[str, str]) -> AsyncIterator[AsyncSession]:
    async for session in _session_for(migrated_database["app"]):
        yield session


@pytest_asyncio.fixture
async def superadmin_session(migrated_database: dict[str, str]) -> AsyncIterator[AsyncSession]:
    async for session in _session_for(migrated_database["superadmin"]):
        yield session
