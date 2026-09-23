"""0008_suppression_audit_deletion

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suppression_list",
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.account_id")
        ),
        sa.Column("phone_hash", sa.LargeBinary, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("campaign_type", postgresql.ENUM(name="campaign_type", create_type=False)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "reason IN ('opt_out','dnd','consent_declined','manual','deleted')",
            name="ck_suppression_list_reason",
        ),
    )
    op.create_index("ix_suppression_list_phone_hash", "suppression_list", ["phone_hash"])

    op.create_table(
        "audit_log",
        sa.Column("log_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_type", sa.Text, nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("before_json", postgresql.JSONB),
        sa.Column("after_json", postgresql.JSONB),
        sa.Column("ip", postgresql.INET),
        sa.Column("user_agent", sa.Text),
        sa.Column("request_id", sa.Text),
        sa.Column("prev_hash", sa.LargeBinary),
        sa.Column("row_hash", sa.LargeBinary, nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "deletion_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "scope", postgresql.ENUM(name="deletion_scope", create_type=False), nullable=False
        ),
        sa.Column("patient_ref_id", postgresql.UUID(as_uuid=True)),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "status",
            postgresql.ENUM(name="deletion_status", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("report", postgresql.JSONB),
    )

    op.create_table(
        "pending_safety_cases",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # Open Question #21 — not in doc 02's DDL; fills the gap doc 07 §3's "per-account DEK wrapped
    # by KMS KEK" description implies. See docs/12_OPEN_QUESTIONS.md.
    op.create_table(
        "account_encryption_keys",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            primary_key=True,
        ),
        sa.Column("wrapped_dek", sa.LargeBinary, nullable=False),
        sa.Column("kek_id", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("rotated_at", sa.TIMESTAMP(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("account_encryption_keys")
    op.drop_table("pending_safety_cases")
    op.drop_table("deletion_requests")
    op.drop_table("audit_log")
    op.drop_index("ix_suppression_list_phone_hash", table_name="suppression_list")
    op.drop_table("suppression_list")
