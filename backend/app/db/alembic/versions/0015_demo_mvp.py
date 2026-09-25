"""0015_demo_mvp

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-25

Demo MVP (browser voice feedback conversation) — see the "Demo MVP" section of
docs/11_BUILD_PLAN.md. Two new tables, both platform/demo-operator config rather than tenant
data (no `account_id` at all): `provider_credentials` (encrypted LLM vendor API keys + selected
model + last-tested status) and `demo_settings` (a single fixed-id row: hospital name, agent
name, voice gender for the demo greeting/persona).

No RLS on either table — same treatment as `cost_rates` (migration 0009), which also has no
`account_id` and is correctly absent from migration 0010's RLS table list. Not covered by
migration 0011's broad grant (that ran before these tables existed), so granted explicitly here,
same pattern as migration 0012's `refresh_tokens`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="not_configured"),
        sa.Column("tested_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_check_constraint(
        "ck_provider_credentials_provider",
        "provider_credentials",
        "provider IN ('gemini','openai')",
    )
    op.create_check_constraint(
        "ck_provider_credentials_status",
        "provider_credentials",
        "status IN ('not_configured','testing','connected','invalid','error')",
    )

    op.create_table(
        "demo_settings",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("hospital_name", sa.Text, nullable=False, server_default="City Hospital"),
        sa.Column("agent_name", sa.Text, nullable=False, server_default="Priya"),
        sa.Column("voice_gender", sa.Text, nullable=False, server_default="female"),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_check_constraint("ck_demo_settings_id", "demo_settings", "id = 1")
    op.create_check_constraint(
        "ck_demo_settings_voice_gender", "demo_settings", "voice_gender IN ('female','male')"
    )
    op.execute(
        "INSERT INTO demo_settings (id, hospital_name, agent_name, voice_gender) "
        "VALUES (1, 'City Hospital', 'Priya', 'female')"
    )

    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON provider_credentials TO {role}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON demo_settings TO {role}")


def downgrade() -> None:
    op.drop_table("demo_settings")
    op.drop_table("provider_credentials")
