"""0006_calls_transcripts

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("call_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "visit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("visits.visit_id"),
            nullable=False,
        ),
        sa.Column(
            "campaign_type",
            postgresql.ENUM(name="campaign_type", create_type=False),
            nullable=False,
            server_default="service_feedback",
        ),
        sa.Column("attempt_no", sa.SmallInteger, nullable=False),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("answered_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "status",
            postgresql.ENUM(name="call_status", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("end_reason", sa.Text),
        sa.Column("provider_call_id", sa.Text),
        sa.Column(
            "consent_state",
            postgresql.ENUM(name="consent_state", create_type=False),
            nullable=False,
            server_default="not_asked",
        ),
        sa.Column("consent_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "respondent",
            postgresql.ENUM(name="respondent_type", create_type=False),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("languages_used", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("duration_sec", sa.Integer),
        sa.Column("billable_sec", sa.Integer),
        sa.Column("turn_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "survey_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("survey_versions.survey_version_id"),
        ),
        sa.Column("state_snapshot", postgresql.JSONB),
        sa.Column("safety_flag", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("needs_human_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("recording_uri", sa.Text),
        sa.Column("recording_retention_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("cost_breakdown", postgresql.JSONB),
        sa.Column("cost_total_paise", sa.Integer),
        sa.Column("prompt_versions", postgresql.JSONB),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("visit_id", "attempt_no"),
        sa.CheckConstraint("attempt_no BETWEEN 1 AND 3", name="ck_calls_attempt_no"),
    )
    op.create_index(
        "ix_calls_account_status_scheduled", "calls", ["account_id", "status", "scheduled_at"]
    )
    op.execute(
        "CREATE UNIQUE INDEX one_active_call_per_visit ON calls (visit_id) "
        "WHERE status IN ('queued','dialing','ringing','answered','in_progress')"
    )

    op.create_table(
        "call_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.call_id"), nullable=False
        ),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_call_events_call_ts", "call_events", ["call_id", "ts"])

    op.create_table(
        "transcripts",
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.call_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer, nullable=False),
        sa.Column("speaker", postgresql.ENUM(name="speaker", create_type=False), nullable=False),
        sa.Column("text_enc", sa.LargeBinary, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=False),
        sa.Column("end_ms", sa.Integer, nullable=False),
        sa.Column("stt_confidence", sa.REAL),
        sa.Column("language", sa.Text),
        sa.Column("retention_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", "turn_index", "speaker"),
    )

    op.create_table(
        "survey_responses",
        sa.Column("response_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.call_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_key", sa.Text, nullable=False),
        sa.Column("field_value", postgresql.JSONB, nullable=False),
        sa.Column("extraction_confidence", sa.REAL, nullable=False),
        sa.Column("source_turn_index", sa.Integer, nullable=False),
        sa.Column("method", sa.Text, nullable=False),
        sa.UniqueConstraint("call_id", "field_key"),
        sa.CheckConstraint("method IN ('deterministic','llm')", name="ck_survey_responses_method"),
    )


def downgrade() -> None:
    op.drop_table("survey_responses")
    op.drop_table("transcripts")
    op.drop_index("ix_call_events_call_ts", table_name="call_events")
    op.drop_table("call_events")
    op.execute("DROP INDEX one_active_call_per_visit")
    op.drop_index("ix_calls_account_status_scheduled", table_name="calls")
    op.drop_table("calls")
