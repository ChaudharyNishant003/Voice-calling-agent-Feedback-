"""0016_conversation_graph

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-26

PRD v2 (Conversation Graph, Safety Layer & Scenario Harness) — Phase 5 schema. Extends existing
tables rather than forking a parallel schema (confirmed decision: reuse `complaints`/`cases` as
they already exist, richer than the PRD's own proposed `pfa_complaints`/`pfa_escalations`).

Deliberate deviation from the PRD's §10 table list: no new `pfa_call_state` table. `calls` already
has a `state_snapshot` JSONB column (migration 0006) doing exactly this job for the existing Demo
MVP engine (resume-after-restart by reconstructing engine state from it each turn) — the new graph
engine reuses that same column/mechanism instead of a second, parallel state store. `current_node`
is just `CallState.node` inside that same JSON blob, so no separate column is needed either.

`visit_type` gains `inpatient`/`emergency` via `ALTER TYPE ... ADD VALUE` — safe inside this
migration's transaction since Postgres 12+ as long as the new values aren't *used* in the same
transaction (they aren't). The downgrade recreates the enum from scratch (Postgres has no
`DROP VALUE`), which only works if no row has actually used the new values yet — true for any
up/down/up test and for this migration's own downgrade path immediately after upgrade.

New tenant tables (`pfa_do_not_call`, `pfa_callbacks`, `pfa_escalations`) follow the exact
account_id + RLS + explicit-grant pattern established in migrations 0010/0011/0015 (0011's blanket
grant only covers tables that existed at that point).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "current_setting('app.account_id', true)::uuid"
_NEW_TENANT_TABLES = ["pfa_do_not_call", "pfa_callbacks", "pfa_escalations"]


def upgrade() -> None:
    # --- demo_settings additions (PRD §10) ---
    op.add_column("demo_settings", sa.Column("hospital_phone", sa.Text, nullable=True))
    op.add_column("demo_settings", sa.Column("escalation_sla_text", sa.Text, nullable=True))
    op.add_column(
        "demo_settings",
        sa.Column("tts_script", sa.Text, nullable=False, server_default="devanagari"),
    )
    op.create_check_constraint(
        "ck_demo_settings_tts_script", "demo_settings", "tts_script IN ('devanagari','roman')"
    )

    # --- visit_type enum: OPD/IPD/DIAGNOSTICS/EMERGENCY (PRD maps OPD->outpatient,
    # DIAGNOSTICS->diagnostic already-existing; IPD->inpatient, EMERGENCY->emergency new) ---
    op.execute("ALTER TYPE visit_type ADD VALUE IF NOT EXISTS 'inpatient'")
    op.execute("ALTER TYPE visit_type ADD VALUE IF NOT EXISTS 'emergency'")

    # --- complaints additions (PRD §6 Node 6's fields not already covered by
    # reason_codes/sentiment/urgency/verbatim_*) ---
    op.add_column("complaints", sa.Column("when_text", sa.Text, nullable=True))
    op.add_column("complaints", sa.Column("where_text", sa.Text, nullable=True))
    op.add_column("complaints", sa.Column("wants_contact", sa.Boolean, nullable=True))
    op.add_column("complaints", sa.Column("preferred_time", sa.Text, nullable=True))
    op.add_column("complaints", sa.Column("staff_name", sa.Text, nullable=True))
    op.add_column("complaints", sa.Column("triggered_by", sa.Text, nullable=True))
    op.create_check_constraint(
        "ck_complaints_triggered_by",
        "complaints",
        "triggered_by IS NULL OR triggered_by IN ('keyword','llm','both')",
    )

    # --- pfa_do_not_call: blocks starting a new demo call for a patient who opted out ---
    op.create_table(
        "pfa_do_not_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("phone_hash", sa.LargeBinary, nullable=False),
        sa.Column(
            "source_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.call_id")
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_pfa_do_not_call_account_phone_hash", "pfa_do_not_call", ["account_id", "phone_hash"]
    )

    # --- pfa_callbacks: recorded, never executed (PRD: "callbacks are recorded, not executed") ---
    op.create_table(
        "pfa_callbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.call_id"), nullable=False
        ),
        sa.Column("preferred_time_text", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "reason IN ('busy','wants_human','language_need','silence','caregiver','repeat_limit')",
            name="ck_pfa_callbacks_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending','completed')", name="ck_pfa_callbacks_status"
        ),
    )

    # --- pfa_escalations: the handoff packet (PRD §7.6), one per triggered escalation ---
    op.create_table(
        "pfa_escalations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
            "complaint_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("complaints.complaint_id")
        ),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.case_id")),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("triggered_by", sa.Text, nullable=False),
        sa.Column("handoff_json", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("acknowledged_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("type IN ('standard','urgent')", name="ck_pfa_escalations_type"),
        sa.CheckConstraint(
            "triggered_by IN ('keyword','llm','both')", name="ck_pfa_escalations_triggered_by"
        ),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','closed')", name="ck_pfa_escalations_status"
        ),
    )
    op.create_index(
        "ix_pfa_escalations_account_status", "pfa_escalations", ["account_id", "status"]
    )

    for table in _NEW_TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (account_id = {_SCOPE}) WITH CHECK (account_id = {_SCOPE})"
        )
        for role in ("pfa_app", "pfa_superadmin"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {role}")


def downgrade() -> None:
    for table in _NEW_TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_pfa_escalations_account_status", table_name="pfa_escalations")
    op.drop_table("pfa_escalations")
    op.drop_table("pfa_callbacks")
    op.drop_index("ix_pfa_do_not_call_account_phone_hash", table_name="pfa_do_not_call")
    op.drop_table("pfa_do_not_call")

    op.drop_constraint("ck_complaints_triggered_by", "complaints", type_="check")
    op.drop_column("complaints", "triggered_by")
    op.drop_column("complaints", "staff_name")
    op.drop_column("complaints", "preferred_time")
    op.drop_column("complaints", "wants_contact")
    op.drop_column("complaints", "where_text")
    op.drop_column("complaints", "when_text")

    # Postgres can't drop a single enum value — recreate the type without the two added values.
    # Only safe if no row has actually used 'inpatient'/'emergency' yet (true right after upgrade).
    op.execute("ALTER TYPE visit_type RENAME TO visit_type_old")
    op.execute("CREATE TYPE visit_type AS ENUM ('outpatient','diagnostic')")
    op.execute(
        "ALTER TABLE visits ALTER COLUMN visit_type TYPE visit_type "
        "USING visit_type::text::visit_type"
    )
    op.execute("DROP TYPE visit_type_old")

    op.drop_constraint("ck_demo_settings_tts_script", "demo_settings", type_="check")
    op.drop_column("demo_settings", "tts_script")
    op.drop_column("demo_settings", "escalation_sla_text")
    op.drop_column("demo_settings", "hospital_phone")
