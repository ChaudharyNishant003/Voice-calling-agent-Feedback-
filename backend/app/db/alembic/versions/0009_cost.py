"""0009_cost

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            primary_key=True,
        ),
        sa.Column("flag", sa.Text, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "cost_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("component", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.Column("paise_per_unit", sa.Numeric(12, 4), nullable=False),
        sa.Column("effective_from", sa.TIMESTAMP(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cost_rates")
    op.drop_table("feature_flags")
