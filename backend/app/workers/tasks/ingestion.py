"""Ingestion batch processing (docs/04_API_SPEC.md §4, docs/06_ERROR_HANDLING_AND_MESSAGES.md
PFA-ING-0xx). Runs the per-row parse/validate/persist loop a 50k-row file needs in the background,
not inside the upload request — `services/ingestion_service.create_batch` already rejected
malformed files (bad extension, too large, wrong encoding, missing header columns, duplicate SHA)
synchronously before this task was ever enqueued, so this only has to handle per-row validation and
the `PFA-ING-003` invalid-row-rate threshold, which both need the fully parsed file.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import uuid7
from app.core.logging import get_logger
from app.core.phone import phone_hash
from app.core.security import encrypt, get_local_kek
from app.db.base import get_superadmin_sessionmaker
from app.db.models.enums import IngestionStatus
from app.db.models.ingestion import IngestionBatch, IngestionRowError
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account, Department, Location
from app.db.repositories.encryption_keys import get_or_create_dek
from app.domain.ingestion_csv import RowIssue, validate_row
from app.services import audit_service, eligibility_service
from app.workers.celery_app import celery_app
from app.workers.task_utils import run_worker_task

logger = get_logger()


class _ThresholdExceeded(Exception):
    pass


@dataclass
class _BatchOutcome:
    rows_total: int
    rows_valid: int
    row_issues: list[RowIssue]
    threshold_exceeded: bool
    error_pct: float


async def _process_rows(
    session: AsyncSession, batch: IngestionBatch, account: Account, rows: list[dict[str, str]]
) -> _BatchOutcome:
    total = len(rows)
    row_issues: list[RowIssue] = []
    created_visit_ids: list[UUID] = []
    error_row_numbers: set[int] = set()

    # Prefetched once per batch rather than queried per row — with up to 50k rows, a per-row
    # `SELECT` (let alone the two this loop would otherwise need, for Patient and Visit lookups)
    # is the difference between this finishing in seconds and blowing the "< 2 min" budget.
    locations = {
        loc.external_location_id: loc
        for loc in (
            await session.scalars(select(Location).where(Location.account_id == batch.account_id))
        ).all()
    }
    departments = {
        dept.code: dept
        for dept in (
            await session.scalars(
                select(Department).where(Department.account_id == batch.account_id)
            )
        ).all()
    }
    patients_by_external_id = {
        p.external_patient_id: p
        for p in (
            await session.scalars(select(Patient).where(Patient.account_id == batch.account_id))
        ).all()
    }
    existing_visit_keys = set(
        (
            await session.scalars(
                select(Visit.external_visit_key).where(Visit.account_id == batch.account_id)
            )
        ).all()
    )
    account_languages = frozenset(account.languages)
    today = date.today()
    pepper = get_settings().phone_hash_pepper
    kek = get_local_kek()

    threshold_exceeded = False
    error_pct = 0.0

    try:
        async with session.begin_nested():
            dek = await get_or_create_dek(session, account.account_id, kek=kek)

            for row_number, raw in enumerate(rows, start=2):  # row 1 is the header
                normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                result = validate_row(
                    row_number,
                    normalized,
                    account_languages=account_languages,
                    date_format=account.ingest_date_format,  # type: ignore[arg-type]
                    today=today,
                )
                row_issues.extend(result.issues)
                if not result.ok or result.row is None:
                    error_row_numbers.add(row_number)
                    continue
                row = result.row

                location = locations.get(row.location_external_id)
                if location is None:
                    row_issues.append(
                        RowIssue(
                            row_number,
                            "location_id",
                            "PFA-ING-018",
                            f"Row {row_number}: location '{row.location_external_id}' isn't set "
                            "up. Add it in Settings.",
                            "error",
                        )
                    )
                    error_row_numbers.add(row_number)
                    continue

                department = departments.get(row.department_raw)
                if department is None:
                    unmapped_code = f"unmapped_{row.department_raw}"
                    department = departments.get(unmapped_code)
                    if department is None:
                        department = Department(
                            department_id=uuid7(),
                            account_id=batch.account_id,
                            code=unmapped_code,
                            name=unmapped_code,
                        )
                        session.add(department)
                        # Flushed immediately (unlike the single end-of-loop flush elsewhere in
                        # this function) — empirically, a `Visit` insert referencing a `Department`
                        # added earlier in the *same* flush batch violates the FK constraint without
                        # an ORM `relationship()` telling SQLAlchemy's unit-of-work to order the two
                        # inserts correctly. New departments are rare (one per distinct unmapped
                        # value), so this isn't a per-row cost.
                        await session.flush()
                        departments[unmapped_code] = department
                    departments[row.department_raw] = department
                    row_issues.append(
                        RowIssue(
                            row_number,
                            "department",
                            "PFA-ING-014",
                            f"Row {row_number}: department '{row.department_raw}' is new and was "
                            "added as unmapped.",
                            "warning",
                        )
                    )

                patient = patients_by_external_id.get(row.external_patient_id)
                if patient is None:
                    patient = Patient(
                        patient_ref_id=uuid7(),
                        account_id=batch.account_id,
                        external_patient_id=row.external_patient_id,
                        phone_hash=bytes.fromhex(phone_hash(row.phone_e164, pepper=pepper)),
                        phone_e164_enc=encrypt(row.phone_e164, dek),
                        phone_last4=row.phone_e164[-4:],
                        preferred_language=row.preferred_language,
                    )
                    session.add(patient)
                    patients_by_external_id[row.external_patient_id] = patient

                # No visit-key column exists in the CSV contract — synthesized from the fields that
                # together identify "this patient's visit on this day at this location". A collision
                # (re-importing the same patient+date+location) is skipped rather than duplicated;
                # there's no error code for this case and skipping is the non-destructive default.
                external_visit_key = (
                    f"{row.external_patient_id}:{row.visit_date.isoformat()}:"
                    f"{row.location_external_id}"
                )
                if external_visit_key in existing_visit_keys:
                    continue
                existing_visit_keys.add(external_visit_key)

                visit = Visit(
                    visit_id=uuid7(),
                    account_id=batch.account_id,
                    location_id=location.location_id,
                    patient_ref_id=patient.patient_ref_id,
                    batch_id=batch.batch_id,
                    external_visit_key=external_visit_key,
                    visit_date=row.visit_date,
                    visit_type=row.visit_type,
                    department_id=department.department_id,
                    doctor_name=row.doctor_name,
                    patient_age=row.patient_age,
                    consent_flag=row.consent_flag,
                )
                session.add(visit)
                created_visit_ids.append(visit.visit_id)

            # One flush for the whole batch, not per row — `visit_id`/`patient_ref_id`/
            # `department_id` were all assigned client-side via `uuid7()` above specifically so
            # nothing downstream in this loop needed a round trip to learn a generated id.
            await session.flush()

            # Based on rows that actually failed validation/lookup, not `total - created` — a row
            # skipped because it re-describes an already-imported visit (see the synthesized-key
            # comment below) is neither invalid nor newly created, and re-uploading a file that
            # mostly overlaps a prior import shouldn't trip `PFA-ING-003` just because of that.
            error_pct = (len(error_row_numbers) / total * 100) if total else 0.0
            if error_pct > account.ingest_error_threshold_pct:
                raise _ThresholdExceeded()
    except _ThresholdExceeded:
        threshold_exceeded = True
        created_visit_ids = []

    if not threshold_exceeded:
        for visit_id in created_visit_ids:
            await eligibility_service.evaluate_and_persist(session, visit_id)

    # `rows_valid`/`rows_rejected` reflect whether a row's *data* was valid, not whether it
    # resulted in a brand-new Visit — a duplicate-visit skip is valid data, just a no-op.
    rows_rejected = total if threshold_exceeded else len(error_row_numbers)
    return _BatchOutcome(
        rows_total=total,
        rows_valid=total - rows_rejected,
        row_issues=row_issues,
        threshold_exceeded=threshold_exceeded,
        error_pct=error_pct,
    )


async def _process_ingestion_batch_async(batch_id: str) -> None:
    async with get_superadmin_sessionmaker()() as session:
        batch = await session.get(IngestionBatch, UUID(batch_id))
        if batch is None:
            logger.error("ingestion.batch_not_found", batch_id=batch_id)
            return
        if batch.content is None:
            logger.error("ingestion.batch_missing_content", batch_id=batch_id)
            return

        account = await session.get(Account, batch.account_id)
        assert account is not None  # FK guarantees this

        text = batch.content.decode("utf-8")  # already validated at upload time
        rows = list(csv.DictReader(io.StringIO(text)))

        outcome = await _process_rows(session, batch, account, rows)

        # Row issues are recorded regardless of the batch's overall outcome — the nested savepoint
        # around Patient/Visit/Department writes rolled those back on a threshold breach, but the
        # errors explaining *why* still need to reach `GET /ingestion/batches/{id}/errors`.
        session.add_all(
            IngestionRowError(
                batch_id=batch.batch_id,
                row_number=issue.row_number,
                field=issue.field,
                error_code=issue.code,
                message=issue.message,
            )
            for issue in outcome.row_issues
        )

        now = datetime.now(UTC)
        batch.rows_total = outcome.rows_total
        batch.rows_valid = outcome.rows_valid
        batch.rows_rejected = outcome.rows_total - outcome.rows_valid
        batch.processed_at = now

        if outcome.threshold_exceeded:
            batch.status = IngestionStatus.failed
            await audit_service.record(
                session,
                account_id=batch.account_id,
                actor_type="system",
                actor_id=batch.uploaded_by,
                action="ingestion.batch_rejected",
                entity_type="ingestion_batch",
                entity_id=batch.batch_id,
                after={"reason": "PFA-ING-003", "error_pct": round(outcome.error_pct, 1)},
            )
        else:
            batch.status = IngestionStatus.processed
            await audit_service.record(
                session,
                account_id=batch.account_id,
                actor_type="system",
                actor_id=batch.uploaded_by,
                action="ingestion.batch_processed",
                entity_type="ingestion_batch",
                entity_id=batch.batch_id,
                after={"rows_total": outcome.rows_total, "rows_valid": outcome.rows_valid},
            )

        await session.commit()
        logger.info(
            "ingestion.batch_finished",
            batch_id=batch_id,
            status=batch.status.value,
            rows_total=outcome.rows_total,
            rows_valid=outcome.rows_valid,
        )


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.tasks.ingestion.process_ingestion_batch", queue="ingest"
)
def process_ingestion_batch(batch_id: str) -> None:
    run_worker_task(_process_ingestion_batch_async(batch_id))
