"""0004_ingestion

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="ingestion_status", create_type=False),
            nullable=False,
            server_default="received",
        ),
        sa.Column("rows_total", sa.Integer),
        sa.Column("rows_valid", sa.Integer),
        sa.Column("rows_rejected", sa.Integer),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True)),
        sa.UniqueConstraint("account_id", "sha256"),
        sa.CheckConstraint("source IN ('sftp','upload')", name="ck_ingestion_batches_source"),
    )

    op.create_table(
        "ingestion_row_errors",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_batches.batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("field", sa.Text),
        sa.Column("error_code", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingestion_row_errors")
    op.drop_table("ingestion_batches")
