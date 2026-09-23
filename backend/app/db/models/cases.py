"""Complaints & cases (docs/02_DATA_MODEL.md §2). `case_events` has no `account_id` column of its
own (tenancy inherited via `case_id`) — see the note in `calls.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import REAL, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import CasePriority, CaseStatus, Sentiment, Urgency, pg_enum


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("calls.call_id"))
    visit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("visits.visit_id"))
    department_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.department_id")
    )
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String))
    sentiment: Mapped[Sentiment] = mapped_column(pg_enum(Sentiment, "sentiment"))
    sentiment_conf: Mapped[float] = mapped_column(REAL)
    urgency: Mapped[Urgency] = mapped_column(pg_enum(Urgency, "urgency"))
    urgency_conf: Mapped[float] = mapped_column(REAL)
    urgency_source: Mapped[str]
    summary: Mapped[str]
    verbatim_enc: Mapped[bytes] = mapped_column(LargeBinary)
    verbatim_start_ms: Mapped[int] = mapped_column(Integer)
    verbatim_end_ms: Mapped[int] = mapped_column(Integer)
    retention_until: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "urgency_source IN ('rule','llm','rule+llm','human')",
            name="ck_complaints_urgency_source",
        ),
        CheckConstraint("verbatim_end_ms > verbatim_start_ms", name="ck_complaints_verbatim_order"),
    )


class Case(Base):
    __tablename__ = "cases"

    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    complaint_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("complaints.complaint_id")
    )
    location_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("locations.location_id")
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.department_id")
    )
    status: Mapped[CaseStatus] = mapped_column(
        pg_enum(CaseStatus, "case_status"), default=CaseStatus.open
    )
    priority: Mapped[CasePriority] = mapped_column(pg_enum(CasePriority, "case_priority"))
    assigned_to: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.user_id")
    )
    acknowledged_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    ack_due_at: Mapped[datetime]
    resolve_due_at: Mapped[datetime | None]
    ack_breached: Mapped[bool] = mapped_column(default=False)
    resolve_breached: Mapped[bool] = mapped_column(default=False)
    resolution_note: Mapped[str | None]
    merged_into_case_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cases.case_id")
    )
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status <> 'closed' OR resolution_note IS NOT NULL", name="ck_cases_close_needs_note"
        ),
        CheckConstraint(
            "status <> 'merged' OR merged_into_case_id IS NOT NULL",
            name="ck_cases_merge_needs_target",
        ),
        Index(
            "ix_cases_account_status_priority_ack", "account_id", "status", "priority", "ack_due_at"
        ),
    )


class CaseEvent(Base):
    __tablename__ = "case_events"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("cases.case_id"))
    actor_type: Mapped[str]
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    from_status: Mapped[CaseStatus | None] = mapped_column(pg_enum(CaseStatus, "case_status"))
    to_status: Mapped[CaseStatus | None] = mapped_column(pg_enum(CaseStatus, "case_status"))
    action: Mapped[str]
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint("actor_type IN ('user','system')", name="ck_case_events_actor_type"),
    )
