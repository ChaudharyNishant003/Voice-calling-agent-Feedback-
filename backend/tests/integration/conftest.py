"""Real-Postgres integration fixtures (docs/08_TESTING_STRATEGY.md §1 — testcontainers).

One container per test session: migrations run once (`upgrade head`), then each test gets its own
transaction via `db_session`/`db_session_as` so tests don't leak state into each other.
"""

from __future__ import annotations

import base64
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


@pytest.fixture(scope="session", autouse=True)
def _isolated_jwt_keys(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """`jwt_private_key_path` defaults to a relative path (`./dev-keys/jwt_ed25519`), and
    `core.security.get_jwt_keys()` is `@lru_cache`d — without this, whichever auth test runs first
    in the session would generate a real keypair file into the backend working directory instead of
    a throwaway one, and every other test would be stuck reusing wherever that landed.
    """
    key_path = tmp_path_factory.mktemp("jwt-keys") / "jwt_ed25519"
    old_value = os.environ.get("JWT_PRIVATE_KEY_PATH")
    os.environ["JWT_PRIVATE_KEY_PATH"] = str(key_path)
    get_settings.cache_clear()
    yield
    if old_value is None:
        os.environ.pop("JWT_PRIVATE_KEY_PATH", None)
    else:
        os.environ["JWT_PRIVATE_KEY_PATH"] = old_value
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _isolated_local_kek() -> Iterator[None]:
    """`local_kek_base64` defaults to `""` (`core/config.py`), and this container doesn't read the
    project's `.env` (its cwd is `/srv`, bind-mounted from `backend/`, not the repo root where
    `.env` lives) — so without this, `core.security.get_local_kek()` (`@lru_cache`d, like
    `get_jwt_keys`) would decode an empty string and raise on first use. Ingestion is the first
    feature that reaches it through the settings-based path rather than a test-local KEK.
    """
    kek_base64 = base64.b64encode(os.urandom(32)).decode()
    old_value = os.environ.get("LOCAL_KEK_BASE64")
    os.environ["LOCAL_KEK_BASE64"] = kek_base64
    get_settings.cache_clear()
    yield
    if old_value is None:
        os.environ.pop("LOCAL_KEK_BASE64", None)
    else:
        os.environ["LOCAL_KEK_BASE64"] = old_value
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _isolated_phone_hash_pepper() -> Iterator[None]:
    """`phone_hash_pepper` defaults to `""` (`core/config.py`) and this container doesn't read the
    project's `.env` (see `_isolated_local_kek` above) — `core.phone.phone_hash` refuses to run with
    an empty pepper, so ingestion (the first feature to hash a phone number through the
    settings-based path rather than a test-local pepper) would fail on every row without this.
    """
    old_value = os.environ.get("PHONE_HASH_PEPPER")
    os.environ["PHONE_HASH_PEPPER"] = "test-pepper-not-for-prod"
    get_settings.cache_clear()
    yield
    if old_value is None:
        os.environ.pop("PHONE_HASH_PEPPER", None)
    else:
        os.environ["PHONE_HASH_PEPPER"] = old_value
    get_settings.cache_clear()


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


@pytest_asyncio.fixture
async def configured_db_env(migrated_database: dict[str, str]) -> AsyncIterator[None]:
    """Points `db.base`'s (`@lru_cache`d) engines at the testcontainers Postgres for this test, then
    disposes and clears them. For any code path that opens its own session internally — via
    `db.base.get_session`/`get_superadmin_session` — rather than taking one as a parameter (the real
    app's FastAPI dependencies; `workers/tasks/*`'s Celery task bodies). `app_session`/
    `superadmin_session` don't need this: they build a fresh engine per test directly against
    `migrated_database`'s URLs, bypassing `db.base` entirely.

    Function-scoped, not session-scoped: pytest-asyncio gives each test its own event loop by
    default, and an engine created in one loop can't be reused from another, so the cached engine is
    disposed and cleared after every test rather than left for the next one.
    """
    from app.db import base as db_base

    old_env = {k: os.environ.get(k) for k in ("DATABASE_URL", "SUPERADMIN_DATABASE_URL")}
    os.environ["DATABASE_URL"] = migrated_database["app"]
    os.environ["SUPERADMIN_DATABASE_URL"] = migrated_database["superadmin"]
    get_settings.cache_clear()
    db_base.get_engine.cache_clear()
    db_base.get_sessionmaker.cache_clear()
    db_base.get_superadmin_engine.cache_clear()
    db_base.get_superadmin_sessionmaker.cache_clear()

    yield

    await db_base.get_engine().dispose()
    await db_base.get_superadmin_engine().dispose()
    db_base.get_engine.cache_clear()
    db_base.get_sessionmaker.cache_clear()
    db_base.get_superadmin_engine.cache_clear()
    db_base.get_superadmin_sessionmaker.cache_clear()

    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


@pytest.fixture
def demo_mode_on() -> Iterator[None]:
    """Shared by every `/api/v1/demo/*` test file (Demo MVP) — `DEMO_MODE` defaults to False."""
    old = os.environ.get("DEMO_MODE")
    os.environ["DEMO_MODE"] = "true"
    get_settings.cache_clear()
    yield
    if old is None:
        os.environ.pop("DEMO_MODE", None)
    else:
        os.environ["DEMO_MODE"] = old
    get_settings.cache_clear()
