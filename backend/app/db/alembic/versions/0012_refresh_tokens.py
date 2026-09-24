"""0012_refresh_tokens

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-24

Open Question #23 — not in doc 02's DDL; fills the gap doc 04 §1 / doc 07 §2's "opaque, hashed in
DB, with rotation and reuse detection" refresh-token description implies. See
docs/12_OPEN_QUESTIONS.md.

`refresh_tokens` has no `account_id` of its own (tenancy inherited via `user_id` -> `users.
account_id`) — RLS uses the same EXISTS-subquery-on-parent pattern migration 0010 used for
`transcripts`/`call_events`/etc.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE = "current_setting('app.account_id', true)::uuid"


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("token_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary, nullable=False, unique=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("replaced_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_refresh_tokens_replaced_by",
        "refresh_tokens",
        "refresh_tokens",
        ["replaced_by"],
        ["token_id"],
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    subquery = (
        f"EXISTS (SELECT 1 FROM users WHERE users.user_id = refresh_tokens.user_id "
        f"AND (users.account_id = {_SCOPE} OR users.account_id IS NULL))"
    )
    op.execute(
        f"CREATE POLICY tenant_isolation ON refresh_tokens "
        f"USING ({subquery}) WITH CHECK ({subquery})"
    )

    # New tables aren't covered by migration 0011's broad grant (that ran before this table
    # existed) — grant explicitly here. UPDATE is needed (unlike audit_log): rotation marks the
    # old row revoked_at/replaced_by.
    for role in ("pfa_app", "pfa_superadmin"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON refresh_tokens TO {role}")


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_constraint("fk_refresh_tokens_replaced_by", "refresh_tokens", type_="foreignkey")
    op.drop_table("refresh_tokens")
