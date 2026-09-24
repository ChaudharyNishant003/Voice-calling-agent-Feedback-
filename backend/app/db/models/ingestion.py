"""Ingestion tables (docs/02_DATA_MODEL.md §2 — ingestion_batches, ingestion_row_errors)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import IngestionStatus, pg_enum


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    batch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    source: Mapped[str]
    filename: Mapped[str]
    sha256: Mapped[str]
    # Open Question #25 (docs/12_OPEN_QUESTIONS.md) — Sprint-1 stopgap until the S3 storage adapter
    # (adapters/storage/s3.py, deferred to Sprint 3) exists.
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[IngestionStatus] = mapped_column(
        pg_enum(IngestionStatus, "ingestion_status"), default=IngestionStatus.received
    )
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_valid: Mapped[int | None] = mapped_column(Integer)
    rows_rejected: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("account_id", "sha256"),
        CheckConstraint("source IN ('sftp','upload')", name="ck_ingestion_batches_source"),
    )


class IngestionRowError(Base):
    __tablename__ = "ingestion_row_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ingestion_batches.batch_id", ondelete="CASCADE")
    )
    row_number: Mapped[int] = mapped_column(Integer)
    field: Mapped[str | None]
    error_code: Mapped[str]
    message: Mapped[str]
