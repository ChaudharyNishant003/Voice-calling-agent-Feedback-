"""Nightly audit-chain verification (docs/07_SECURITY_AND_COMPLIANCE.md §6 — 'nightly job verifies
the chain and alerts on break'). Real alert routing (paging, doc 09 §4) lands with observability
work later; this logs a structured critical event per break, which is enough for a log-based alert
rule to pick up in the meantime.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import get_superadmin_sessionmaker
from app.db.models.compliance import AuditLogEntry
from app.domain.audit_chain import verify_chain
from app.workers.celery_app import celery_app

logger = get_logger()


async def _verify_audit_chain_async() -> list[int]:
    """Returns the `log_id`s of any broken rows (empty = chain intact).

    Connects as `pfa_superadmin` (BYPASSRLS, `db.base.get_superadmin_sessionmaker`), not the
    regular app engine — this job verifies the *entire* table across every tenant, and `pfa_app`'s
    RLS policy on `audit_log` only matches rows where `account_id` equals the current session's
    scope (or is NULL, for platform-wide entries). Without a specific tenant scope set, `pfa_app`
    would only ever see the NULL-account_id rows.
    """
    async with get_superadmin_sessionmaker()() as session:
        rows = list(
            (await session.scalars(select(AuditLogEntry).order_by(AuditLogEntry.log_id))).all()
        )

    breaks = verify_chain(rows)

    if breaks:
        for b in breaks:
            logger.error("audit.chain.broken", log_id=b.log_id, severity="critical")
    else:
        logger.info("audit.chain.verified", rows_checked=len(rows))

    return [b.log_id for b in breaks]


@celery_app.task(name="app.workers.tasks.audit.verify_audit_chain")  # type: ignore[untyped-decorator]
def verify_audit_chain() -> list[int]:
    return asyncio.run(_verify_audit_chain_async())
