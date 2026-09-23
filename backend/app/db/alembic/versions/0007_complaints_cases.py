"""0007_complaints_cases

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("complaint_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.call_id"), nullable=False
        ),
        sa.Column(
            "visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("visits.visit_id"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.department_id"),
        ),
        sa.Column("reason_codes", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column(
            "sentiment", postgresql.ENUM(name="sentiment", create_type=False), nullable=False
        ),
        sa.Column("sentiment_conf", sa.REAL, nullable=False),
        sa.Column("urgency", postgresql.ENUM(name="urgency", create_type=False), nullable=False),
        sa.Column("urgency_conf", sa.REAL, nullable=False),
        sa.Column("urgency_source", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("verbatim_enc", sa.LargeBinary, nullable=False),
        sa.Column("verbatim_start_ms", sa.Integer, nullable=False),
        sa.Column("verbatim_end_ms", sa.Integer, nullable=False),
        sa.Column("retention_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "urgency_source IN ('rule','llm','rule+llm','human')",
            name="ck_complaints_urgency_source",
        ),
        sa.CheckConstraint(
            "verbatim_end_ms > verbatim_start_ms", name="ck_complaints_verbatim_order"
        ),
    )

    op.create_table(
        "cases",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "complaint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("complaints.complaint_id"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.location_id"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.department_id"),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="case_status", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "priority", postgresql.ENUM(name="case_priority", create_type=False), nullable=False
        ),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.user_id")),
        sa.Column("acknowledged_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("ack_due_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolve_due_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("ack_breached", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("resolve_breached", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("resolution_note", sa.Text),
        sa.Column("merged_into_case_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reopen_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status <> 'closed' OR resolution_note IS NOT NULL", name="ck_cases_close_needs_note"
        ),
        sa.CheckConstraint(
            "status <> 'merged' OR merged_into_case_id IS NOT NULL",
            name="ck_cases_merge_needs_target",
        ),
    )
    op.create_foreign_key(
        "fk_cases_merged_into_case_id", "cases", "cases", ["merged_into_case_id"], ["case_id"]
    )
    op.create_index(
        "ix_cases_account_status_priority_ack",
        "cases",
        ["account_id", "status", "priority", "ack_due_at"],
    )

    op.create_table(
        "case_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.case_id"), nullable=False
        ),
        sa.Column("actor_type", sa.Text, nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("from_status", postgresql.ENUM(name="case_status", create_type=False)),
        sa.Column("to_status", postgresql.ENUM(name="case_status", create_type=False)),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("actor_type IN ('user','system')", name="ck_case_events_actor_type"),
    )


def downgrade() -> None:
    op.drop_table("case_events")
    op.drop_index("ix_cases_account_status_priority_ack", table_name="cases")
    op.drop_constraint("fk_cases_merged_into_case_id", "cases", type_="foreignkey")
    op.drop_table("cases")
    op.drop_table("complaints")
