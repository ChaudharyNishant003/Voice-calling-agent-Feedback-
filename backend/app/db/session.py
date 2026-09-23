"""Row-Level Security session scoping (docs/02_DATA_MODEL.md §5).

`SET LOCAL` only affects the current transaction, so callers must invoke this inside an open
transaction (e.g. right after `session.begin()`) — it has no effect once that transaction commits.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_account_scope(session: AsyncSession, account_id: UUID) -> None:
    """Bind this transaction's `app.account_id` so RLS policies can filter tenant tables by it.

    `SET LOCAL` itself doesn't accept bind parameters (it wants a literal), so this uses
    `set_config(..., is_local=true)` instead — same effect, safely parameterised.
    """
    await session.execute(
        text("SELECT set_config('app.account_id', :account_id, true)"),
        {"account_id": str(account_id)},
    )
