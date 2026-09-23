"""Patients & visits (docs/02_DATA_MODEL.md §2). Phone numbers are never stored in plaintext —
`phone_hash` (HMAC) and `phone_e164_enc` (AES-GCM envelope) only, per doc 07 §3.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    ForeignKey,
    LargeBinary,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import EligibilityStatus, SuppressionReason, VisitType, pg_enum


class Patient(Base):
    __tablename__ = "patients"

    patient_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    external_patient_id: Mapped[str]
    phone_hash: Mapped[bytes] = mapped_column(LargeBinary)
    phone_e164_enc: Mapped[bytes] = mapped_column(LargeBinary)
    phone_last4: Mapped[str] = mapped_column(CHAR(4))
    preferred_language: Mapped[str | None]
    opt_out: Mapped[bool] = mapped_column(default=False)
    opt_out_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (UniqueConstraint("account_id", "external_patient_id"),)


class Visit(Base):
    __tablename__ = "visits"

    visit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    location_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.location_id")
    )
    patient_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("patients.patient_ref_id")
    )
    batch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ingestion_batches.batch_id")
    )
    external_visit_key: Mapped[str]
    visit_date: Mapped[date] = mapped_column(Date)
    visit_type: Mapped[VisitType] = mapped_column(pg_enum(VisitType, "visit_type"))
    department_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.department_id")
    )
    doctor_name: Mapped[str | None]
    patient_age: Mapped[int] = mapped_column(SmallInteger)
    consent_flag: Mapped[bool | None]
    eligibility_status: Mapped[EligibilityStatus] = mapped_column(
        pg_enum(EligibilityStatus, "eligibility_status"), default=EligibilityStatus.pending
    )
    suppression_reason: Mapped[SuppressionReason | None] = mapped_column(
        pg_enum(SuppressionReason, "suppression_reason")
    )
    eligibility_evaluated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("account_id", "external_visit_key"),
        CheckConstraint("patient_age BETWEEN 0 AND 130", name="ck_visits_patient_age"),
    )
