"""0001_enums

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly docs/02_DATA_MODEL.md §1's CREATE TYPE statements.
_ENUM_STATEMENTS: list[tuple[str, str]] = [
    (
        "account_status",
        "CREATE TYPE account_status AS ENUM ('onboarding','live','paused','offboarded')",
    ),
    ("visit_type", "CREATE TYPE visit_type AS ENUM ('outpatient','diagnostic')"),
    (
        "eligibility_status",
        "CREATE TYPE eligibility_status AS ENUM ('pending','eligible','suppressed','review')",
    ),
    (
        "suppression_reason",
        "CREATE TYPE suppression_reason AS ENUM ("
        "'minor','invalid_number','opt_out','dnd','duplicate_encounter','already_called_visit',"
        "'frequency_cap','stale_visit','shared_number_review','consent_declined_visit',"
        "'out_of_scope_visit_type','missing_required_field','deleted_patient')",
    ),
    (
        "call_status",
        "CREATE TYPE call_status AS ENUM ("
        "'queued','dialing','ringing','answered','in_progress','completed','partial',"
        "'abandoned_pre_consent','consent_declined','voicemail','no_answer','busy',"
        "'failed_telephony','failed_system','cancelled')",
    ),
    (
        "consent_state",
        "CREATE TYPE consent_state AS ENUM "
        "('not_asked','granted','declined','withdrawn','granted_unrecorded')",
    ),
    ("respondent_type", "CREATE TYPE respondent_type AS ENUM ('patient','proxy','unknown')"),
    ("campaign_type", "CREATE TYPE campaign_type AS ENUM ('service_feedback','promotional')"),
    ("sentiment", "CREATE TYPE sentiment AS ENUM ('negative','neutral','positive')"),
    ("urgency", "CREATE TYPE urgency AS ENUM ('routine','service_failure','safety_concern')"),
    (
        "case_status",
        "CREATE TYPE case_status AS ENUM ('open','acknowledged','assigned','in_progress',"
        "'resolved','closed','reopened','merged','invalid')",
    ),
    ("case_priority", "CREATE TYPE case_priority AS ENUM ('p1','p2','p3')"),
    (
        "user_role",
        "CREATE TYPE user_role AS ENUM ('super_admin','admin','quality','dept_owner','read_only')",
    ),
    ("speaker", "CREATE TYPE speaker AS ENUM ('agent','patient','system')"),
    ("deletion_scope", "CREATE TYPE deletion_scope AS ENUM ('patient','account')"),
    (
        "deletion_status",
        "CREATE TYPE deletion_status AS ENUM "
        "('requested','approved','running','completed','failed','rejected')",
    ),
    (
        "ingestion_status",
        "CREATE TYPE ingestion_status AS ENUM "
        "('received','validating','validated','failed','processed')",
    ),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    for _name, statement in _ENUM_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for name, _statement in reversed(_ENUM_STATEMENTS):
        op.execute(f"DROP TYPE {name}")
    # Extensions are left in place on downgrade — other databases/roles may depend on them and
    # DROP EXTENSION is not safely reversible in a shared dev/staging cluster.
