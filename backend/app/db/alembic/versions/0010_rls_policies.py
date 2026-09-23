"""0010_rls_policies

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24

Row-Level Security (docs/02_DATA_MODEL.md §5): every tenant table filters by
`current_setting('app.account_id', true)::uuid`, set per-transaction by `db/session.py`. The `true`
(missing_ok) argument makes an unset scope evaluate to NULL rather than raise — NULL never equals a
real account_id, so a connection with no scope set sees nothing (fails closed).

Enforcement only matters for a role that isn't the table owner (migration 0011 creates `pfa_app` for
exactly this reason) — Postgres RLS is bypassed by owners/superusers regardless of these policies.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "current_setting('app.account_id', true)::uuid"

# Tables with their own `account_id` column — straightforward equality policy.
_DIRECT_TABLES = [
    "accounts",
    "locations",
    "departments",
    "users",
    "survey_versions",
    "ingestion_batches",
    "patients",
    "visits",
    "calls",
    "complaints",
    "cases",
    "deletion_requests",
    "pending_safety_cases",
    "account_encryption_keys",
    "feature_flags",
]

# Child tables with no account_id of their own — tenancy inherited via a parent FK (see the note
# in db/models/calls.py and cases.py; doc 02 §5 states every tenant table has account_id but the
# literal DDL doesn't give these four a column).
_CHILD_TABLES = [
    ("ingestion_row_errors", "ingestion_batches", "batch_id", "batch_id"),
    ("call_events", "calls", "call_id", "call_id"),
    ("transcripts", "calls", "call_id", "call_id"),
    ("survey_responses", "calls", "call_id", "call_id"),
    ("case_events", "cases", "case_id", "case_id"),
]

# account_id is nullable here (NULL = platform-wide / system-level), visible to every tenant.
_NULLABLE_ACCOUNT_TABLES = ["suppression_list", "audit_log"]


def upgrade() -> None:
    for table in [*_DIRECT_TABLES, *_NULLABLE_ACCOUNT_TABLES]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    for table in _DIRECT_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (account_id = {_SCOPE}) WITH CHECK (account_id = {_SCOPE})"
        )

    for table in _NULLABLE_ACCOUNT_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (account_id = {_SCOPE} OR account_id IS NULL) "
            f"WITH CHECK (account_id = {_SCOPE} OR account_id IS NULL)"
        )

    for table, parent, child_fk, parent_pk in _CHILD_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        subquery = (
            f"EXISTS (SELECT 1 FROM {parent} WHERE {parent}.{parent_pk} = {table}.{child_fk} "
            f"AND {parent}.account_id = {_SCOPE})"
        )
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({subquery}) WITH CHECK ({subquery})"
        )


def downgrade() -> None:
    for table, *_rest in _CHILD_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in [*_DIRECT_TABLES, *_NULLABLE_ACCOUNT_TABLES]:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
