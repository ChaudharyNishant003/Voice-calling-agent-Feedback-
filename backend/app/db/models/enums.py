"""SQLAlchemy-facing enum wiring (docs/02_DATA_MODEL.md §1).

The actual vocabulary lives in `app.domain.enums` — this module only adds the SQLAlchemy-specific
`pg_enum()` helper and re-exports the classes, so model columns keep doing
`from app.db.models.enums import VisitType, pg_enum` while `domain/eligibility.py` (pure — no
`app.db` imports allowed) can use the same vocabulary via `app.domain.enums` directly.

Migration 0001 creates the actual `CREATE TYPE ... AS ENUM` statements; model columns reference
these via `pg_enum()` with `create_type=False` so Alembic never tries to create them a second time.
"""

from __future__ import annotations

import enum

from sqlalchemy.dialects.postgresql import ENUM as PGEnum

from app.domain.enums import (
    AccountStatus,
    CallStatus,
    CampaignType,
    CasePriority,
    CaseStatus,
    ConsentState,
    DeletionScope,
    DeletionStatus,
    EligibilityStatus,
    IngestionStatus,
    RespondentType,
    Sentiment,
    Speaker,
    SuppressionReason,
    Urgency,
    UserRole,
    VisitType,
)

__all__ = [
    "AccountStatus",
    "CallStatus",
    "CampaignType",
    "CasePriority",
    "CaseStatus",
    "ConsentState",
    "DeletionScope",
    "DeletionStatus",
    "EligibilityStatus",
    "IngestionStatus",
    "RespondentType",
    "Sentiment",
    "Speaker",
    "SuppressionReason",
    "Urgency",
    "UserRole",
    "VisitType",
    "pg_enum",
]


def pg_enum(python_enum: type[enum.Enum], name: str) -> PGEnum:
    return PGEnum(
        python_enum, name=name, create_type=False, values_callable=lambda e: [m.value for m in e]
    )
