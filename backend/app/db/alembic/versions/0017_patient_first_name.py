"""0017_patient_first_name

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-27

PRD v2 §11: the patient/visit form takes `patient_first_name (required)`, and the results page
(§11) displays it per row. `patients` has no name field at all today — by design, per CLAUDE.md
rule 8 (data minimisation: phone_hash for matching, encrypted phone only where dialling needs it,
"no clinical data beyond what the patient volunteered"). A first name isn't clinical data and the
patient volunteers it to the operator starting the call either way, so it's added the same way the
phone number already is: encrypted at rest (`first_name_enc`), nullable (existing Sprint 1
ingestion-created patients never had one and shouldn't need a backfill).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("first_name_enc", sa.LargeBinary, nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "first_name_enc")
