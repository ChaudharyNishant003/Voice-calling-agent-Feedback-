"""Ingestion I/O layer (docs/04_API_SPEC.md §4, docs/06_ERROR_HANDLING_AND_MESSAGES.md PFA-ING-0xx).

`create_batch` is the synchronous (request-time) half: batch-level pre-checks (size, extension,
duplicate SHA-256) and enqueuing the Celery job. Per-row parsing/validation and the actual
`Patient`/`Visit` writes happen in `workers/tasks/ingestion.py`, since a 50k-row file has to process
in the background, not inside the HTTP request.
"""

from __future__ import annotations

import csv
import hashlib
import io
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, PayloadTooLargeError, ValidationError
from app.db.models.ingestion import IngestionBatch, IngestionRowError
from app.domain.ingestion_csv import REQUIRED_COLUMNS
from app.services import audit_service

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 50_000

_TOO_LARGE_MESSAGE = "Files can be up to 20 MB and 50,000 rows. Split the file and try again."


class DuplicateBatchError(ConflictError):
    pass


async def create_batch(
    session: AsyncSession,
    *,
    account_id: UUID,
    filename: str,
    content: bytes,
    uploaded_by: UUID,
) -> IngestionBatch:
    if not filename.lower().endswith(".csv"):
        raise ValidationError("PFA-ING-001", message="Please upload a .csv file.")

    if len(content) > MAX_FILE_BYTES:
        raise PayloadTooLargeError("PFA-ING-005", message=_TOO_LARGE_MESSAGE)
    # Cheap upper-bound row count precheck (newline count) — the worker does the real per-row count
    # once it has decoded the file; this just rejects obviously-oversized files before enqueuing.
    if content.count(b"\n") > MAX_ROWS + 1:
        raise PayloadTooLargeError("PFA-ING-005", message=_TOO_LARGE_MESSAGE)

    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "PFA-ING-004", message="Save the file as CSV UTF-8 and upload again."
        ) from exc

    header = next(csv.reader(io.StringIO(text)), None)
    header_columns = {(c or "").strip().lower() for c in (header or [])}
    missing = REQUIRED_COLUMNS - header_columns
    if missing:
        raise ValidationError(
            "PFA-ING-002",
            message=(
                f"The file is missing these columns: {', '.join(sorted(missing))}. "
                "Download the template to check."
            ),
            details={"columns": sorted(missing)},
        )

    sha256 = hashlib.sha256(content).hexdigest()

    # Checked before inserting (not insert-then-catch-IntegrityError): the caller's request-scoped
    # session is wrapped in one transaction for the whole request (`api/deps.py`), and recovering
    # from a failed INSERT would need a savepoint just to keep that transaction usable afterward.
    # Checking first is simpler and the unique constraint remains the real backstop for the narrow
    # concurrent-duplicate-upload race this doesn't fully close.
    existing = await session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.account_id == account_id, IngestionBatch.sha256 == sha256
        )
    )
    if existing is not None:
        raise DuplicateBatchError(
            "PFA-ING-006",
            message=f"This file was already uploaded on {existing.created_at.date().isoformat()}.",
        )

    batch = IngestionBatch(
        account_id=account_id,
        source="upload",
        filename=filename,
        sha256=sha256,
        content=content,
        uploaded_by=uploaded_by,
    )
    session.add(batch)
    await session.flush()

    await audit_service.record(
        session,
        account_id=account_id,
        actor_type="user",
        actor_id=uploaded_by,
        action="ingestion.batch_created",
        entity_type="ingestion_batch",
        entity_id=batch.batch_id,
        after={"filename": filename, "sha256": sha256},
    )
    return batch


async def get_batch(session: AsyncSession, batch_id: UUID) -> IngestionBatch | None:
    return await session.get(IngestionBatch, batch_id)


async def list_batches(session: AsyncSession, account_id: UUID) -> list[IngestionBatch]:
    stmt = (
        select(IngestionBatch)
        .where(IngestionBatch.account_id == account_id)
        .order_by(IngestionBatch.created_at.desc())
    )
    return list((await session.scalars(stmt)).all())


async def list_batch_errors(session: AsyncSession, batch_id: UUID) -> list[IngestionRowError]:
    stmt = (
        select(IngestionRowError)
        .where(IngestionRowError.batch_id == batch_id)
        .order_by(IngestionRowError.row_number.asc())
    )
    return list((await session.scalars(stmt)).all())
