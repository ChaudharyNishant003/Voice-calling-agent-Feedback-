"""Per-account DEK storage (Open Question #21 — see docs/12_OPEN_QUESTIONS.md and
docs/07_SECURITY_AND_COMPLIANCE.md §3). Only `KMS_PROVIDER=local` is implemented; AWS/GCP KMS is a
later deployment-sprint concern (doc 10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_dek, unwrap_dek, wrap_dek
from app.db.models.compliance import AccountEncryptionKey

LOCAL_KEK_ID = "local-dev"


async def get_or_create_dek(session: AsyncSession, account_id: UUID, *, kek: bytes) -> bytes:
    """Return the account's unwrapped DEK, generating and persisting one on first use."""
    row = await session.scalar(
        select(AccountEncryptionKey).where(AccountEncryptionKey.account_id == account_id)
    )
    if row is not None:
        return unwrap_dek(row.wrapped_dek, kek)

    dek = generate_dek()
    session.add(
        AccountEncryptionKey(
            account_id=account_id,
            wrapped_dek=wrap_dek(dek, kek),
            kek_id=LOCAL_KEK_ID,
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return dek
