"""upgrade head -> downgrade base -> upgrade head (doc 08 §1 / docs/02_DATA_MODEL.md §6).

Uses its own container rather than the shared `migrated_database` fixture other integration tests
use, since this test's whole point is to mutate schema state destructively (downgrade to base) —
sharing a container with tests that assume an already-migrated, stable schema would be fragile.
"""

from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def test_upgrade_downgrade_upgrade_cycle_is_clean() -> None:
    with PostgresContainer(
        "postgres:16", username="pfa", password="pfa", dbname="pfa"
    ) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        url = f"postgresql+asyncpg://pfa:pfa@{host}:{port}/pfa"

        old_url = os.environ.get("MIGRATION_DATABASE_URL")
        os.environ["MIGRATION_DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            alembic_cfg = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
            alembic_cfg.set_main_option(
                "script_location", os.path.join(_BACKEND_ROOT, "app", "db", "alembic")
            )

            command.upgrade(alembic_cfg, "head")
            command.downgrade(alembic_cfg, "base")
            command.upgrade(alembic_cfg, "head")
        finally:
            if old_url is None:
                os.environ.pop("MIGRATION_DATABASE_URL", None)
            else:
                os.environ["MIGRATION_DATABASE_URL"] = old_url
            get_settings.cache_clear()
