"""Tenancy tables (docs/02_DATA_MODEL.md §2 — accounts, locations, departments, users)."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base
from app.db.models.enums import AccountStatus, UserRole, pg_enum


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str]
    display_name_tts: Mapped[str]
    tier: Mapped[str] = mapped_column(default="standard")
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus, "account_status"), default=AccountStatus.onboarding
    )
    timezone: Mapped[str] = mapped_column(default="Asia/Kolkata")
    contact_window_start: Mapped[time] = mapped_column(default=time(10, 0))
    contact_window_end: Mapped[time] = mapped_column(default=time(19, 0))
    contact_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), default=lambda: [1, 2, 3, 4, 5, 6]
    )
    holidays: Mapped[list[date]] = mapped_column(ARRAY(Date), default=list)
    max_concurrent_calls: Mapped[int] = mapped_column(default=10)
    daily_call_cap: Mapped[int] = mapped_column(default=500)
    survey_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    primary_metric: Mapped[str] = mapped_column(default="csat")
    languages: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["en", "hi"])
    allow_proxy_feedback: Mapped[bool] = mapped_column(default=False)
    recency_window_hours: Mapped[int] = mapped_column(default=72)
    dedupe_window_days: Mapped[int] = mapped_column(default=7)
    frequency_cap_days: Mapped[int] = mapped_column(default=30)
    frequency_cap_count: Mapped[int] = mapped_column(default=1)
    shared_number_threshold: Mapped[int] = mapped_column(default=3)
    retention_policy: Mapped[dict[str, object]] = mapped_column(JSONB)
    sla_config: Mapped[dict[str, object]] = mapped_column(JSONB)
    emergency_number: Mapped[str] = mapped_column(default="112")
    hospital_urgent_line: Mapped[str | None]
    caller_id_e164: Mapped[str]
    default_case_owner_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "max_concurrent_calls BETWEEN 1 AND 200", name="ck_accounts_max_concurrent_calls"
        ),
        CheckConstraint("primary_metric IN ('nps','csat')", name="ck_accounts_primary_metric"),
    )


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    external_location_id: Mapped[str]
    name: Mapped[str]
    address: Mapped[str | None]
    timezone: Mapped[str | None]

    __table_args__ = (UniqueConstraint("account_id", "external_location_id"),)


class Department(Base):
    __tablename__ = "departments"

    department_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    code: Mapped[str]
    name: Mapped[str]
    tts_name_en: Mapped[str | None]
    tts_name_hi: Mapped[str | None]
    owner_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))

    __table_args__ = (UniqueConstraint("account_id", "code"),)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str]
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    password_hash: Mapped[str | None]
    mfa_secret_enc: Mapped[bytes | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    location_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    department_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), default=list)
    last_login_at: Mapped[datetime | None]
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
