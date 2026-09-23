"""0011_grants

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24

Creates the two roles the RLS policies in 0010 are actually enforced against (docs/02_DATA_MODEL.md
§5 / §3): `pfa_app` (the app's runtime connection — RLS applies because it isn't the table owner)
and `pfa_superadmin` (BYPASSRLS, for audited cross-tenant access).

Privilege choice: SELECT/INSERT/UPDATE everywhere except `audit_log`. No blanket DELETE grant:
nothing in the spec deletes rows outright — retention/deletion workflows tombstone/anonymise via
UPDATE (doc 07 §8), and `ON DELETE CASCADE` FKs aren't exercised by any documented app flow. If a
later sprint needs row deletion somewhere specific, grant it there with a clear reason rather than
broadening this.

`audit_log` is append-only for both roles: no UPDATE, ever — that's the actual integrity property
doc 07 §6's tamper-evidence chain depends on (a stored `row_hash`/`prev_hash` can never be quietly
rewritten). Both roles keep SELECT + INSERT on it: `audit_service.record()` (the only code path
that's allowed to write a row) has to read the current chain tail to compute the next `prev_hash`,
which is impossible if the role that writes can't also read; doc 07 §6 separately requires an
"admin UI view + API" for MVP and a nightly integrity-verification job, both of which read it too.
Earlier drafts of this migration read doc 02 §3's "pfa_app has INSERT only on audit_log" as
excluding SELECT as well — that reading turned out to be self-defeating (verified by an actual
integration test failure: `pfa_app` couldn't read back the chain tail it needs to write the next
row), so it's interpreted here as "no UPDATE/DELETE" instead, which is the constraint that actually
matters for tamper-evidence.
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

    # audit_log is append-only: no UPDATE for either role (see module docstring for why SELECT
    # stays granted — the broad loop above already covers it).
    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"REVOKE UPDATE ON audit_log FROM {role}")


def downgrade() -> None:
    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
        op.execute(f"REVOKE CONNECT ON DATABASE pfa FROM {role}")
    op.execute("DROP ROLE IF EXISTS pfa_app")
    op.execute("DROP ROLE IF EXISTS pfa_superadmin")
