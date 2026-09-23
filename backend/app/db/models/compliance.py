"""Suppression, audit, deletion (docs/02_DATA_MODEL.md §2) + `account_encryption_keys` (Open
Question #21 — a doc-02 schema gap filled to match doc 07 §3's described envelope-encryption model).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, LargeBinary
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import CampaignType, DeletionScope, DeletionStatus, pg_enum


class SuppressionEntry(Base):
    __tablename__ = "suppression_list"

    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    phone_hash: Mapped[bytes] = mapped_column(LargeBinary)
    reason: Mapped[str]
    source: Mapped[str]
    campaign_type: Mapped[CampaignType | None] = mapped_column(
        pg_enum(CampaignType, "campaign_type")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "reason IN ('opt_out','dnd','consent_declined','manual','deleted')",
            name="ck_suppression_list_reason",
        ),
        Index("ix_suppression_list_phone_hash", "phone_hash"),
    )


class AuditLogEntry(Base):
    """Append-only (`pfa_app` grant is INSERT-only, doc 02 §3 — enforced in migration 0011)."""

    __tablename__ = "audit_log"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    actor_type: Mapped[str]
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    before_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    request_id: Mapped[str | None]
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    row_hash: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"

    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    scope: Mapped[DeletionScope] = mapped_column(pg_enum(DeletionScope, "deletion_scope"))
    patient_ref_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    requested_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[DeletionStatus] = mapped_column(
        pg_enum(DeletionStatus, "deletion_status"), default=DeletionStatus.requested
    )
    reason: Mapped[str]
    due_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
    report: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class PendingSafetyCase(Base):
    """Fallback if a P1 case insert fails in-call (PFA-SAF-004, doc 02 §2)."""

    __tablename__ = "pending_safety_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AccountEncryptionKey(Base):
    """Wrapped per-account DEK (Open Question #21 — doc 02 has no table for doc 07 §3's described
    "per-account DEK wrapped by KMS KEK" model; this fills that gap rather than deriving keys, which
    would silently drop doc 07's stated per-account DEK rotation capability).
    """

    __tablename__ = "account_encryption_keys"

    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id"), primary_key=True
    )
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    rotated_at: Mapped[datetime | None]
