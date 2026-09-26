"""Demo MVP config (docs/11_BUILD_PLAN.md "Demo MVP" section) — platform/demo-operator settings,
not tenant data. No RLS; see migration 0015's docstring for why.

`DoNotCall`/`Callback` (migration 0016, PRD v2 §10) ARE tenant data (account_id + RLS), unlike the
rest of this module — they live here rather than in `cases.py` because they're demo-call lifecycle
records, not case-tracking ones (`PfaEscalation`, the third new PRD v2 table, sits in `cases.py`
instead since it FKs to both `complaints` and `cases`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, SmallInteger
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.ids import uuid7
from app.db.base import Base


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"

    provider: Mapped[str] = mapped_column(primary_key=True)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    model: Mapped[str]
    status: Mapped[str] = mapped_column(default="not_configured")
    tested_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DemoSettings(Base):
    __tablename__ = "demo_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    hospital_name: Mapped[str] = mapped_column(default="City Hospital")
    agent_name: Mapped[str] = mapped_column(default="Priya")
    voice_gender: Mapped[str] = mapped_column(default="female")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Added by migration 0016 (PRD v2 §10).
    hospital_phone: Mapped[str | None]
    escalation_sla_text: Mapped[str | None]
    tts_script: Mapped[str] = mapped_column(default="devanagari")

    __table_args__ = (
        CheckConstraint(
            "tts_script IN ('devanagari','roman')", name="ck_demo_settings_tts_script"
        ),
    )


class DoNotCall(Base):
    """Starting a new demo call is blocked for a patient on this list (PRD v2 §10)."""

    __tablename__ = "pfa_do_not_call"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    phone_hash: Mapped[bytes] = mapped_column(LargeBinary)
    source_call_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.call_id")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Callback(Base):
    """Recorded, never executed (PRD v2 §2: "callbacks are recorded, not executed")."""

    __tablename__ = "pfa_callbacks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id")
    )
    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("calls.call_id"))
    preferred_time_text: Mapped[str | None]
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "reason IN ('busy','wants_human','language_need','silence','caregiver','repeat_limit')",
            name="ck_pfa_callbacks_reason",
        ),
        CheckConstraint("status IN ('pending','completed')", name="ck_pfa_callbacks_status"),
    )
