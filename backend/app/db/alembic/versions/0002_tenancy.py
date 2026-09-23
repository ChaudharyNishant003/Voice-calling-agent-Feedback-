"""0002_tenancy

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pg_enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("display_name_tts", sa.Text, nullable=False),
        sa.Column("tier", sa.Text, nullable=False, server_default="standard"),
        sa.Column(
            "status", _pg_enum("account_status"), nullable=False, server_default="onboarding"
        ),
        sa.Column("timezone", sa.Text, nullable=False, server_default="Asia/Kolkata"),
        sa.Column("contact_window_start", sa.Time, nullable=False, server_default="10:00"),
        sa.Column("contact_window_end", sa.Time, nullable=False, server_default="19:00"),
        sa.Column(
            "contact_days",
            postgresql.ARRAY(sa.SmallInteger),
            nullable=False,
            server_default="{1,2,3,4,5,6}",
        ),
        sa.Column("holidays", postgresql.ARRAY(sa.Date), nullable=False, server_default="{}"),
        sa.Column("max_concurrent_calls", sa.Integer, nullable=False, server_default="10"),
        sa.Column("daily_call_cap", sa.Integer, nullable=False, server_default="500"),
        sa.Column("survey_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("primary_metric", sa.Text, nullable=False, server_default="csat"),
        sa.Column("languages", postgresql.ARRAY(sa.Text), nullable=False, server_default="{en,hi}"),
        sa.Column("allow_proxy_feedback", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("recency_window_hours", sa.Integer, nullable=False, server_default="72"),
        sa.Column("dedupe_window_days", sa.Integer, nullable=False, server_default="7"),
        sa.Column("frequency_cap_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("frequency_cap_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("shared_number_threshold", sa.Integer, nullable=False, server_default="3"),
        sa.Column("retention_policy", postgresql.JSONB, nullable=False),
        sa.Column("sla_config", postgresql.JSONB, nullable=False),
        sa.Column("emergency_number", sa.Text, nullable=False, server_default="112"),
        sa.Column("hospital_urgent_line", sa.Text),
        sa.Column("caller_id_e164", sa.Text, nullable=False),
        sa.Column("default_case_owner_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "max_concurrent_calls BETWEEN 1 AND 200", name="ck_accounts_max_concurrent_calls"
        ),
        sa.CheckConstraint("primary_metric IN ('nps','csat')", name="ck_accounts_primary_metric"),
    )

    op.create_table(
        "locations",
        sa.Column("location_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("external_location_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("address", sa.Text),
        sa.Column("timezone", sa.Text),
        sa.UniqueConstraint("account_id", "external_location_id"),
    )

    op.create_table(
        "departments",
        sa.Column("department_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("tts_name_en", sa.Text),
        sa.Column("tts_name_hi", sa.Text),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("account_id", "code"),
    )

    op.create_table(
        "users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.account_id")
        ),
        sa.Column("email", postgresql.CITEXT, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("role", _pg_enum("user_role"), nullable=False),
        sa.Column("password_hash", sa.Text),
        sa.Column("mfa_secret_enc", sa.LargeBinary),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "location_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "department_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("departments")
    op.drop_table("locations")
    op.drop_table("accounts")
