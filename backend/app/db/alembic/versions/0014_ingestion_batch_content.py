"""0014_ingestion_batch_content

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-24

Open Question #25 — the worker that parses an uploaded CSV needs the raw bytes, but nothing
persists them anywhere: `adapters/storage/s3.py`'s `ObjectStorageAdapter` is a deliberate stub
("lands alongside audio work in Sprint 3"), and doc 02 has no other column for it. Stores the raw
bytes directly on `ingestion_batches` as a Sprint-1 stopgap rather than building the S3 adapter
early or passing up to 20 MB through the Celery broker as a task argument. No retention/purge job
exists for this column yet either — Sprint 1 doesn't include retention work; tracked as part of the
same open question rather than silently left unbounded.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_batches", sa.Column("content", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_batches", "content")
