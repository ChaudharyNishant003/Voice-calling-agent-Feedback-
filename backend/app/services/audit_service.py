"""Audit log writer (docs/07_SECURITY_AND_COMPLIANCE.md §6). This is the only supported way
application code creates an `audit_log` row — never `session.add(AuditLogEntry(...))` directly,
since the hash chain has to be built correctly on every insert.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.compliance import AuditLogEntry
from app.domain.audit_chain import compute_row_hash

# Arbitrary fixed key for a session-level advisory lock scoped to this transaction
# (`pg_advisory_xact_lock` auto-releases at commit/rollback). Serializes every `record()` call
# across all connections so `prev_hash` always reflects the true chain tail — a
# `SELECT ... ORDER BY log_id DESC LIMIT 1 FOR UPDATE` looks equivalent but isn't: two concurrent
# transactions can each lock a *different* already-latest row before either commits, both computing
# `prev_hash` from a row that's no longer actually last once the other commits, forking the chain.
_AUDIT_CHAIN_LOCK_KEY = 8_723_471_230_981_223


async def record(
    session: AsyncSession,
    *,
    account_id: UUID | None,
    actor_type: str,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
    ip: str | IPv4Address | IPv6Address | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> AuditLogEntry:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _AUDIT_CHAIN_LOCK_KEY}
    )

    prev_hash = await session.scalar(
        select(AuditLogEntry.row_hash).order_by(AuditLogEntry.log_id.desc()).limit(1)
    )

    # Canonical string form up front: asyncpg may hand back INET columns as ipaddress objects on
    # read-back, and `canonical_json`'s `default=str` on those has to match what we hash here.
    ip_str = str(ip_address(ip)) if ip is not None else None
    created_at = datetime.now(UTC)
    hashed = {
        "account_id": account_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_json": before,
        "after_json": after,
        "ip": ip_str,
        "user_agent": user_agent,
        "request_id": request_id,
        "created_at": created_at,
    }
    row_hash = compute_row_hash(prev_hash, hashed)

    entry = AuditLogEntry(
        account_id=account_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        ip=ip_str,
        user_agent=user_agent,
        request_id=request_id,
        prev_hash=prev_hash,
        row_hash=row_hash,
        created_at=created_at,
    )
    session.add(entry)
    await session.flush()
    return entry
