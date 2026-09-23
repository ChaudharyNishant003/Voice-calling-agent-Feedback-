"""0005_patients_visits

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("patient_ref_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column("external_patient_id", sa.Text, nullable=False),
        sa.Column("phone_hash", sa.LargeBinary, nullable=False),
        sa.Column("phone_e164_enc", sa.LargeBinary, nullable=False),
        sa.Column("phone_last4", sa.CHAR(4), nullable=False),
        sa.Column("preferred_language", sa.Text),
        sa.Column("opt_out", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("opt_out_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("account_id", "external_patient_id"),
    )
    op.create_index("ix_patients_account_phone_hash", "patients", ["account_id", "phone_hash"])

    op.create_table(
        "visits",
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.location_id"),
            nullable=False,
        ),
        sa.Column(
            "patient_ref_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.patient_ref_id"),
            nullable=False,
        ),
        sa.Column(
            "batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingestion_batches.batch_id")
        ),
        sa.Column("external_visit_key", sa.Text, nullable=False),
        sa.Column("visit_date", sa.Date, nullable=False),
        sa.Column(
            "visit_type", postgresql.ENUM(name="visit_type", create_type=False), nullable=False
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.department_id"),
            nullable=False,
        ),
        sa.Column("doctor_name", sa.Text),
        sa.Column("patient_age", sa.SmallInteger, nullable=False),
        sa.Column("consent_flag", sa.Boolean),
        sa.Column(
            "eligibility_status",
            postgresql.ENUM(name="eligibility_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "suppression_reason", postgresql.ENUM(name="suppression_reason", create_type=False)
        ),
        sa.Column("eligibility_evaluated_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("account_id", "external_visit_key"),
        sa.CheckConstraint("patient_age BETWEEN 0 AND 130", name="ck_visits_patient_age"),
    )
    op.create_index(
        "ix_visits_account_eligibility_date",
        "visits",
        ["account_id", "eligibility_status", "visit_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_visits_account_eligibility_date", table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_patients_account_phone_hash", table_name="patients")
    op.drop_table("patients")
