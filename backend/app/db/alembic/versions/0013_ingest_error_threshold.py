"""0013_ingest_error_threshold

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-24

Open Question #24 — doc 04 §4 describes two per-account ingestion knobs that doc 02's DDL never
defined a column for: the "too many invalid rows" batch-rejection threshold (`PFA-ING-003`,
"configurable", default 30%) and the visit-date format ("`YYYY-MM-DD` or `DD-MM-YYYY` (account
setting)"). Both added here alongside the account's other per-tenant knobs (`frequency_cap_count`
etc., migration 0002) rather than guessed at parse time — an ambiguous date like `03-04-2026` is a
real data-correctness risk (feeds recency/dedup rules), so this is a deterministic setting, not
auto-detection.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "ingest_error_threshold_pct", sa.SmallInteger(), nullable=False, server_default="30"
        ),
    )
    op.create_check_constraint(
        "ck_accounts_ingest_error_threshold_pct",
        "accounts",
        "ingest_error_threshold_pct BETWEEN 1 AND 100",
    )
    op.add_column(
        "accounts",
        sa.Column(
            "ingest_date_format", sa.String(), nullable=False, server_default="YYYY-MM-DD"
        ),
    )
    op.create_check_constraint(
        "ck_accounts_ingest_date_format",
        "accounts",
        "ingest_date_format IN ('YYYY-MM-DD','DD-MM-YYYY')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_ingest_date_format", "accounts", type_="check")
    op.drop_column("accounts", "ingest_date_format")
    op.drop_constraint("ck_accounts_ingest_error_threshold_pct", "accounts", type_="check")
    op.drop_column("accounts", "ingest_error_threshold_pct")
