"""Platform config (docs/02_DATA_MODEL.md §2 — feature_flags, cost_rates)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.account_id"), primary_key=True
    )
    flag: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)


class CostRate(Base):
    __tablename__ = "cost_rates"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    component: Mapped[str]
    provider: Mapped[str]
    unit: Mapped[str]
    paise_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    effective_from: Mapped[datetime]
