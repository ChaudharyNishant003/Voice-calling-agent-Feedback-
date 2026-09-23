"""Calls & call-adjacent tables (docs/02_DATA_MODEL.md §2 — calls, call_events, transcripts,
survey_responses). `call_events`, `transcripts`, `survey_responses` have no `account_id` column of
their own (tenancy inherited via `call_id`) — RLS for them uses an EXISTS subquery, see migration
0010 and Open Question tracking in the Sprint 1 plan.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import (
    CallStatus,
    CampaignType,
    ConsentState,
    RespondentType,
    Speaker,
    pg_enum,
)


class Call(Base):
    __tablename__ = "calls"

    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    visit_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("visits.visit_id"))
    campaign_type: Mapped[CampaignType] = mapped_column(
        pg_enum(CampaignType, "campaign_type"), default=CampaignType.service_feedback
    )
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    scheduled_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    answered_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    status: Mapped[CallStatus] = mapped_column(
        pg_enum(CallStatus, "call_status"), default=CallStatus.queued
    )
    end_reason: Mapped[str | None]
    provider_call_id: Mapped[str | None]
    consent_state: Mapped[ConsentState] = mapped_column(
        pg_enum(ConsentState, "consent_state"), default=ConsentState.not_asked
    )
    consent_at: Mapped[datetime | None]
    respondent: Mapped[RespondentType] = mapped_column(
        pg_enum(RespondentType, "respondent_type"), default=RespondentType.unknown
    )
    languages_used: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    billable_sec: Mapped[int | None] = mapped_column(Integer)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    survey_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("survey_versions.survey_version_id")
    )
    state_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    safety_flag: Mapped[bool] = mapped_column(default=False)
    needs_human_review: Mapped[bool] = mapped_column(default=False)
    recording_uri: Mapped[str | None]
    recording_retention_until: Mapped[datetime | None]
    cost_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    cost_total_paise: Mapped[int | None] = mapped_column(Integer)
    prompt_versions: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("visit_id", "attempt_no"),
        CheckConstraint("attempt_no BETWEEN 1 AND 3", name="ck_calls_attempt_no"),
        Index("ix_calls_account_status_scheduled", "account_id", "status", "scheduled_at"),
    )


class CallEvent(Base):
    __tablename__ = "call_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("calls.call_id"))
    ts: Mapped[datetime] = mapped_column(server_default=func.now())
    type: Mapped[str]
    data: Mapped[dict[str, object]] = mapped_column(JSONB)

    __table_args__ = (Index("ix_call_events_call_ts", "call_id", "ts"),)


class Transcript(Base):
    __tablename__ = "transcripts"

    transcript_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7
    )
    call_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.call_id", ondelete="CASCADE")
    )
    turn_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[Speaker] = mapped_column(pg_enum(Speaker, "speaker"))
    text_enc: Mapped[bytes] = mapped_column(LargeBinary)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    stt_confidence: Mapped[float | None] = mapped_column(REAL)
    language: Mapped[str | None]
    retention_until: Mapped[datetime]

    __table_args__ = (UniqueConstraint("call_id", "turn_index", "speaker"),)


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    response_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    call_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.call_id", ondelete="CASCADE")
    )
    field_key: Mapped[str]
    field_value: Mapped[dict[str, object]] = mapped_column(JSONB)
    extraction_confidence: Mapped[float] = mapped_column(REAL)
    source_turn_index: Mapped[int] = mapped_column(Integer)
    method: Mapped[str]

    __table_args__ = (
        UniqueConstraint("call_id", "field_key"),
        CheckConstraint("method IN ('deterministic','llm')", name="ck_survey_responses_method"),
    )
