"""Demo MVP config (docs/11_BUILD_PLAN.md "Demo MVP" section) — platform/demo-operator settings,
not tenant data. No RLS; see migration 0015's docstring for why.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import LargeBinary, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

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
