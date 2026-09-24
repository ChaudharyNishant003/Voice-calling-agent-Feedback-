"""50k-row ingestion performance (docs/08_TESTING_STRATEGY.md §6 — "50k-row performance
(< 2 min)"). Excluded from the default `pytest tests/integration` run (see pyproject.toml's
`addopts`/`markers`) — a wall-clock budget check, not a per-commit correctness gate.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenancy import Account, Department, Location, User
from app.db.session import set_account_scope
from app.domain.enums import UserRole
from app.services import ingestion_service
from app.workers.tasks.ingestion import _process_ingestion_batch_async

_ROW_COUNT = 50_000
_TIME_BUDGET_S = 120

_HEADER = (
    "external_patient_id,phone,visit_date,visit_type,department,doctor_name,"
    "preferred_language,patient_age,consent_flag,location_id\n"
)


def _synthetic_csv(rows: int) -> bytes:
    today = date.today() - timedelta(days=1)
    lines = [_HEADER]
    for i in range(rows):
        # Valid Indian mobile numbers: 10 digits starting 6-9, made unique per row.
        phone = f"9{i:09d}"[:10]
        lines.append(
            f"PAT-{i},{phone},{today.isoformat()},outpatient,cardiology,,en,45,yes,loc-1\n"
        )
    return "".join(lines).encode("utf-8")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_50k_row_batch_processes_within_two_minutes(
    configured_db_env: None,
    app_session: AsyncSession,
    superadmin_session: AsyncSession,
) -> None:
    del configured_db_env
    account = Account(
        name="Perf Test Hospital",
        display_name_tts="Perf Test Hospital",
        caller_id_e164="+911234567890",
        retention_policy={"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        sla_config={"p1": {"ack": 1, "resolve": 24}},
    )
    superadmin_session.add(account)
    await superadmin_session.commit()

    location = Location(account_id=account.account_id, external_location_id="loc-1", name="Main")
    department = Department(account_id=account.account_id, code="cardiology", name="Cardiology")
    uploader = User(
        account_id=account.account_id,
        email=f"perf-{account.account_id}@example.com",
        name="Perf Uploader",
        role=UserRole.quality,
    )
    superadmin_session.add_all([location, department, uploader])
    await superadmin_session.commit()

    content = _synthetic_csv(_ROW_COUNT)

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        batch = await ingestion_service.create_batch(
            app_session,
            account_id=account.account_id,
            filename="perf.csv",
            content=content,
            uploaded_by=uploader.user_id,
        )

    started = time.monotonic()
    await _process_ingestion_batch_async(str(batch.batch_id))
    elapsed = time.monotonic() - started

    processed = await superadmin_session.get(type(batch), batch.batch_id)
    assert processed is not None
    assert processed.rows_valid == _ROW_COUNT
    assert elapsed < _TIME_BUDGET_S, f"processing took {elapsed:.1f}s, budget is {_TIME_BUDGET_S}s"
