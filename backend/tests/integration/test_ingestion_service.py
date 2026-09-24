"""Real Postgres: `services/ingestion_service.create_batch` (batch-level pre-checks) and
`workers/tasks/ingestion._process_ingestion_batch_async` (per-row parsing, `Patient`/`Visit`
creation, eligibility evaluation, the `PFA-ING-003` threshold) — docs/04_API_SPEC.md §4,
docs/08_TESTING_STRATEGY.md §6.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.db.models.compliance import AuditLogEntry
from app.db.models.enums import EligibilityStatus, IngestionStatus
from app.db.models.ingestion import IngestionBatch, IngestionRowError
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account, Department, Location, User
from app.db.session import set_account_scope
from app.domain.enums import UserRole
from app.services import ingestion_service
from app.services.ingestion_service import DuplicateBatchError
from app.workers.tasks.ingestion import _process_ingestion_batch_async

_HEADER = (
    "external_patient_id,phone,visit_date,visit_type,department,doctor_name,"
    "preferred_language,patient_age,consent_flag,location_id\n"
)
# Today, not a hardcoded past date — the default `recency_window_hours` (72h, `stale_visit` rule
# in `domain/eligibility.py`) would otherwise silently suppress these visits once enough real time
# has passed since this file was written.
_TODAY = date.today().isoformat()


def _account(**overrides: object) -> Account:
    defaults: dict[str, object] = {
        "name": "Ingestion Test Hospital",
        "display_name_tts": "Ingestion Test Hospital",
        "caller_id_e164": "+911234567890",
        "retention_policy": {"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        "sla_config": {"p1": {"ack": 1, "resolve": 24}},
    }
    defaults.update(overrides)
    return Account(**defaults)


def _row(
    patient_id: str = "PAT-1",
    phone: str = "9876543210",
    visit_date: str = _TODAY,
    visit_type: str = "outpatient",
    department: str = "cardiology",
    age: str = "45",
    location: str = "loc-1",
    doctor_name: str = "",
) -> str:
    return (
        f"{patient_id},{phone},{visit_date},{visit_type},{department},{doctor_name},"
        f"en,{age},yes,{location}\n"
    )


@pytest.fixture
async def base_setup(superadmin_session: AsyncSession) -> dict[str, object]:
    account = _account()
    superadmin_session.add(account)
    await superadmin_session.commit()

    location = Location(account_id=account.account_id, external_location_id="loc-1", name="Main")
    department = Department(account_id=account.account_id, code="cardiology", name="Cardiology")
    uploader = User(
        account_id=account.account_id,
        email=f"uploader-{account.account_id}@example.com",
        name="Uploader",
        role=UserRole.quality,
    )
    superadmin_session.add_all([location, department, uploader])
    await superadmin_session.commit()

    return {
        "account": account,
        "location": location,
        "department": department,
        "uploader": uploader,
    }


@pytest.mark.asyncio
async def test_create_batch_happy_path_audits_and_stores_content(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = (_HEADER + _row()).encode("utf-8")

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        batch = await ingestion_service.create_batch(
            app_session,
            account_id=account.account_id,
            filename="patients.csv",
            content=content,
            uploaded_by=uploader.user_id,
        )

    assert batch.status == IngestionStatus.received
    assert batch.content == content

    audit_rows = list(
        (
            await superadmin_session.scalars(
                select(AuditLogEntry).where(AuditLogEntry.action == "ingestion.batch_created")
            )
        ).all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].entity_id == batch.batch_id


@pytest.mark.asyncio
async def test_create_batch_rejects_duplicate_sha(
    app_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = (_HEADER + _row()).encode("utf-8")

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        await ingestion_service.create_batch(
            app_session,
            account_id=account.account_id,
            filename="patients.csv",
            content=content,
            uploaded_by=uploader.user_id,
        )

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        with pytest.raises(DuplicateBatchError) as exc_info:
            await ingestion_service.create_batch(
                app_session,
                account_id=account.account_id,
                filename="patients-again.csv",
                content=content,
                uploaded_by=uploader.user_id,
            )
    assert exc_info.value.code == "PFA-ING-006"


@pytest.mark.asyncio
async def test_create_batch_rejects_missing_required_columns(
    app_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = b"external_patient_id,phone\nPAT-1,9876543210\n"

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        with pytest.raises(ValidationError) as exc_info:
            await ingestion_service.create_batch(
                app_session,
                account_id=account.account_id,
                filename="patients.csv",
                content=content,
                uploaded_by=uploader.user_id,
            )
    assert exc_info.value.code == "PFA-ING-002"


@pytest.mark.asyncio
async def test_create_batch_rejects_non_csv_extension(
    app_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        with pytest.raises(ValidationError) as exc_info:
            await ingestion_service.create_batch(
                app_session,
                account_id=account.account_id,
                filename="patients.xlsx",
                content=b"whatever",
                uploaded_by=uploader.user_id,
            )
    assert exc_info.value.code == "PFA-ING-001"


async def _create_and_process(
    app_session: AsyncSession,
    account: Account,
    uploader: User,
    content: bytes,
    filename: str = "patients.csv",
) -> UUID:
    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        batch = await ingestion_service.create_batch(
            app_session,
            account_id=account.account_id,
            filename=filename,
            content=content,
            uploaded_by=uploader.user_id,
        )
    batch_id = batch.batch_id
    await _process_ingestion_batch_async(str(batch_id))
    return batch_id


@pytest.mark.asyncio
async def test_valid_csv_is_processed_with_visits_and_eligibility(
    configured_db_env: None,
    app_session: AsyncSession,
    superadmin_session: AsyncSession,
    base_setup: dict[str, object],
) -> None:
    del configured_db_env
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = (_HEADER + _row(patient_id="PAT-100") + _row(patient_id="PAT-101")).encode("utf-8")

    batch_id = await _create_and_process(app_session, account, uploader, content)

    batch = await superadmin_session.get(IngestionBatch, batch_id)
    assert batch is not None
    assert batch.status == IngestionStatus.processed
    assert batch.rows_total == 2
    assert batch.rows_valid == 2
    assert batch.rows_rejected == 0

    visits = list(
        (await superadmin_session.scalars(select(Visit).where(Visit.batch_id == batch_id))).all()
    )
    assert len(visits) == 2
    for visit in visits:
        assert visit.eligibility_status == EligibilityStatus.eligible

    patients = list(
        (
            await superadmin_session.scalars(
                select(Patient).where(Patient.account_id == account.account_id)
            )
        ).all()
    )
    assert len(patients) == 2
    for patient in patients:
        assert patient.phone_e164_enc != b""  # encrypted, not stored plain
        assert isinstance(patient.phone_hash, bytes)


@pytest.mark.asyncio
async def test_unmapped_department_is_auto_created_and_warned(
    configured_db_env: None,
    app_session: AsyncSession,
    superadmin_session: AsyncSession,
    base_setup: dict[str, object],
) -> None:
    del configured_db_env
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = (_HEADER + _row(patient_id="PAT-200", department="neurology")).encode("utf-8")

    batch_id = await _create_and_process(app_session, account, uploader, content)

    department = await superadmin_session.scalar(
        select(Department).where(
            Department.account_id == account.account_id, Department.code == "unmapped_neurology"
        )
    )
    assert department is not None

    warnings = list(
        (
            await superadmin_session.scalars(
                select(IngestionRowError).where(
                    IngestionRowError.batch_id == batch_id,
                    IngestionRowError.error_code == "PFA-ING-014",
                )
            )
        ).all()
    )
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_over_threshold_batch_is_rejected_and_persists_nothing(
    configured_db_env: None,
    app_session: AsyncSession,
    superadmin_session: AsyncSession,
    base_setup: dict[str, object],
) -> None:
    del configured_db_env
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]

    # 1 valid row, 3 invalid (bad age) — 75% error rate, over the default 30% threshold.
    rows = _row(patient_id="PAT-300")
    for i in range(3):
        rows += _row(patient_id=f"PAT-30{i + 1}", age="not-a-number")
    content = (_HEADER + rows).encode("utf-8")

    batch_id = await _create_and_process(app_session, account, uploader, content)

    batch = await superadmin_session.get(IngestionBatch, batch_id)
    assert batch is not None
    assert batch.status == IngestionStatus.failed
    assert batch.rows_total == 4
    assert batch.rows_valid == 0
    assert batch.rows_rejected == 4

    visits = list(
        (await superadmin_session.scalars(select(Visit).where(Visit.batch_id == batch_id))).all()
    )
    assert visits == []
    patients = list(
        (
            await superadmin_session.scalars(
                select(Patient).where(Patient.account_id == account.account_id)
            )
        ).all()
    )
    assert patients == []

    # The row errors explaining *why* still persist even though the Patient/Visit rows rolled back.
    errors = list(
        (
            await superadmin_session.scalars(
                select(IngestionRowError).where(IngestionRowError.batch_id == batch_id)
            )
        ).all()
    )
    assert len(errors) == 3
    assert all(e.error_code == "PFA-ING-016" for e in errors)

    rejection_audit = list(
        (
            await superadmin_session.scalars(
                select(AuditLogEntry).where(AuditLogEntry.action == "ingestion.batch_rejected")
            )
        ).all()
    )
    assert len(rejection_audit) == 1


@pytest.mark.asyncio
async def test_reimporting_same_patient_visit_location_skips_duplicate_visit(
    configured_db_env: None,
    app_session: AsyncSession,
    superadmin_session: AsyncSession,
    base_setup: dict[str, object],
) -> None:
    del configured_db_env
    account: Account = base_setup["account"]  # type: ignore[assignment]
    uploader: User = base_setup["uploader"]  # type: ignore[assignment]
    content = (_HEADER + _row(patient_id="PAT-400")).encode("utf-8")

    await _create_and_process(app_session, account, uploader, content, filename="a.csv")
    # A different file (different SHA, so not blocked by PFA-ING-006) describing the same patient,
    # visit date, and location — `doctor_name` varies just to make the file bytes differ.
    second_content = (
        _HEADER + _row(patient_id="PAT-400", doctor_name="Dr. Iyer")
    ).encode("utf-8")
    second_batch_id = await _create_and_process(
        app_session, account, uploader, second_content, filename="b.csv"
    )

    second_batch = await superadmin_session.get(IngestionBatch, second_batch_id)
    assert second_batch is not None
    # The row's data is valid (and doesn't count toward PFA-ING-003) even though it results in no
    # new Visit — "valid" and "newly created" are different things; see the Visit count below.
    assert second_batch.status == IngestionStatus.processed
    assert second_batch.rows_valid == 1
    assert second_batch.rows_rejected == 0

    visits = list(
        (
            await superadmin_session.scalars(
                select(Visit).where(Visit.account_id == account.account_id)
            )
        ).all()
    )
    assert len(visits) == 1
