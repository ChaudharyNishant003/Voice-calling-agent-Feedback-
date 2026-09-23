"""0011_grants

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24

Creates the two roles the RLS policies in 0010 are actually enforced against (docs/02_DATA_MODEL.md
§5 / §3): `pfa_app` (the app's runtime connection — RLS applies because it isn't the table owner)
and `pfa_superadmin` (BYPASSRLS, for audited cross-tenant access).

Privilege choice: SELECT/INSERT/UPDATE everywhere except `audit_log` (INSERT-only, doc 02 §3 —
append-only, tamper evidence depends on this). No blanket DELETE grant: nothing in the spec deletes
rows outright — retention/deletion workflows tombstone/anonymise via UPDATE (doc 07 §8), and
`ON DELETE CASCADE` FKs aren't exercised by any documented app flow. If a later sprint needs row
deletion somewhere specific, grant it there with a clear reason rather than broadening this.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.config import get_settings

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    settings = get_settings()
    app_password = _sql_literal(settings.pfa_app_db_password)
    superadmin_password = _sql_literal(settings.pfa_superadmin_db_password)

    op.execute(
        f"DO $$ BEGIN "
        f"CREATE ROLE pfa_app LOGIN PASSWORD {app_password}; "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        f"DO $$ BEGIN "
        f"CREATE ROLE pfa_superadmin LOGIN BYPASSRLS PASSWORD {superadmin_password}; "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )

    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"GRANT CONNECT ON DATABASE pfa TO {role}")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {role}")
        op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {role}")

    # audit_log is append-only for both roles: revoke SELECT/UPDATE, leave INSERT.
    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"REVOKE SELECT, UPDATE ON audit_log FROM {role}")


def downgrade() -> None:
    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
        op.execute(f"REVOKE CONNECT ON DATABASE pfa FROM {role}")
    op.execute("DROP ROLE IF EXISTS pfa_app")
    op.execute("DROP ROLE IF EXISTS pfa_superadmin")
