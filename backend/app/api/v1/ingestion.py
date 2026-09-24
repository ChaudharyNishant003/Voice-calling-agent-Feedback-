"""Ingestion endpoints (docs/04_API_SPEC.md §4). CSV parsing/validation happens in
`workers/tasks/ingestion.process_ingestion_batch`, enqueued here only *after* the request's
transaction has committed (`BackgroundTasks` runs once the response is being sent, which is after
`api/deps.py`'s `get_db_session` dependency has closed/committed) — enqueuing any earlier would let
the worker query for a batch row that isn't visible yet in another connection.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, require
from app.core.errors import NotFoundError
from app.core.ids import format_id
from app.core.security import Permission
from app.db.models.ingestion import IngestionBatch, IngestionRowError
from app.db.models.tenancy import User
from app.domain.ingestion_csv import REQUIRED_COLUMNS
from app.services import ingestion_service
from app.workers.tasks.ingestion import process_ingestion_batch

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_TEMPLATE_COLUMNS = sorted(REQUIRED_COLUMNS | {"doctor_name", "preferred_language", "consent_flag"})
_TEMPLATE_CSV = ",".join(_TEMPLATE_COLUMNS) + "\n"


class BatchResponse(BaseModel):
    batch_id: str
    status: str
    filename: str
    rows_total: int | None
    rows_valid: int | None
    rows_rejected: int | None
    created_at: datetime
    processed_at: datetime | None


class RowErrorResponse(BaseModel):
    row_number: int
    field: str | None
    error_code: str
    message: str


def _batch_response(batch: IngestionBatch) -> BatchResponse:
    return BatchResponse(
        batch_id=format_id("ingestion_batch", batch.batch_id),
        status=batch.status.value,
        filename=batch.filename,
        rows_total=batch.rows_total,
        rows_valid=batch.rows_valid,
        rows_rejected=batch.rows_rejected,
        created_at=batch.created_at,
        processed_at=batch.processed_at,
    )


@router.post("/uploads")
async def upload(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require(Permission.upload_lists)),
) -> BatchResponse:
    assert user.account_id is not None  # upload_lists is never granted to super_admin (doc 07 §1)
    content = await file.read()
    batch = await ingestion_service.create_batch(
        session,
        account_id=user.account_id,
        filename=file.filename or "upload.csv",
        content=content,
        uploaded_by=user.user_id,
    )
    batch_id = str(batch.batch_id)
    background_tasks.add_task(process_ingestion_batch.delay, batch_id)
    return _batch_response(batch)


@router.get("/batches")
async def list_batches(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require(Permission.upload_lists)),
) -> list[BatchResponse]:
    assert user.account_id is not None
    batches = await ingestion_service.list_batches(session, user.account_id)
    return [_batch_response(b) for b in batches]


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require(Permission.upload_lists)),
) -> BatchResponse:
    batch = await ingestion_service.get_batch(session, batch_id)
    if batch is None:
        raise NotFoundError("PFA-ING-007", message="That upload wasn't found.")
    return _batch_response(batch)


@router.get("/batches/{batch_id}/errors")
async def get_batch_errors(
    batch_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require(Permission.upload_lists)),
) -> list[RowErrorResponse]:
    batch = await ingestion_service.get_batch(session, batch_id)
    if batch is None:
        raise NotFoundError("PFA-ING-007", message="That upload wasn't found.")
    errors = await ingestion_service.list_batch_errors(session, batch_id)
    return [_row_error_response(e) for e in errors]


def _row_error_response(error: IngestionRowError) -> RowErrorResponse:
    return RowErrorResponse(
        row_number=error.row_number,
        field=error.field,
        error_code=error.error_code,
        message=error.message,
    )


@router.get("/template.csv")
async def template_csv(user: User = Depends(get_current_user)) -> PlainTextResponse:
    # doc 04 §4 lists role "any" — same "any authenticated user, no specific permission bit"
    # treatment as `/me` (see api/deps.py), not literally public/unauthenticated.
    del user
    return PlainTextResponse(_TEMPLATE_CSV, media_type="text/csv")
