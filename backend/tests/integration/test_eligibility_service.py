"""Real Postgres: `eligibility_service.evaluate_and_persist` against seeded fixtures covering each
rule, and `resolve_review` writing both the visit update and a matching audit row in one transaction
(docs/03_CALL_FLOW_AND_CONVERSATION.md §1, docs/07_SECURITY_AND_COMPLIANCE.md §6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.calls import Call
from app.db.models.compliance import AuditLogEntry, SuppressionEntry
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account, Department, Location, User
from app.db.session import set_account_scope
from app.domain.enums import CallStatus, EligibilityStatus, SuppressionReason, UserRole, VisitType
from app.services import eligibility_service


def _account(**overrides: object) -> Account:
    defaults: dict[str, object] = {
        "name": "Elig Test Hospital",
        "display_name_tts": "Elig Test Hospital",
        "caller_id_e164": "+911234567890",
        "retention_policy": {"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        "sla_config": {"p1": {"ack": 1, "resolve": 24}},
        "recency_window_hours": 72,
        "dedupe_window_days": 7,
        "frequency_cap_days": 30,
        "frequency_cap_count": 1,
        "shared_number_threshold": 3,
    }
    defaults.update(overrides)
    return Account(**defaults)


def _patient(account_id: UUID, phone_hash: bytes, **overrides: object) -> Patient:
    defaults: dict[str, object] = {
        "account_id": account_id,
        "external_patient_id": f"ext-{phone_hash.hex()[:8]}",
        "phone_hash": phone_hash,
        "phone_e164_enc": b"not-real-ciphertext",
        "phone_last4": "3210",
    }
    defaults.update(overrides)
    return Patient(**defaults)


def _visit(
    account_id: UUID,
    location_id: UUID,
    department_id: UUID,
    patient_ref_id: UUID,
    **overrides: object,
) -> Visit:
    defaults: dict[str, object] = {
        "account_id": account_id,
        "location_id": location_id,
        "patient_ref_id": patient_ref_id,
        "department_id": department_id,
        "external_visit_key": f"visit-{patient_ref_id}-{overrides.get('visit_date', date.today())}",
        "visit_date": date.today(),
        "visit_type": VisitType.outpatient,
        "patient_age": 45,
    }
    defaults.update(overrides)
    return Visit(**defaults)


@pytest.fixture
async def base_setup(superadmin_session: AsyncSession) -> dict[str, object]:
    account = _account()
    superadmin_session.add(account)
    await superadmin_session.commit()

    location = Location(account_id=account.account_id, external_location_id="loc-1", name="Main")
    department = Department(account_id=account.account_id, code="cardiology", name="Cardiology")
    superadmin_session.add_all([location, department])
    await superadmin_session.commit()

    return {"account": account, "location": location, "department": department}


@pytest.mark.asyncio
async def test_happy_path_becomes_eligible(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    location: Location = base_setup["location"]  # type: ignore[assignment]
    department: Department = base_setup["department"]  # type: ignore[assignment]

    patient = _patient(account.account_id, b"\x01" * 32)
    superadmin_session.add(patient)
    await superadmin_session.commit()

    visit = _visit(
        account.account_id, location.location_id, department.department_id, patient.patient_ref_id
    )
    superadmin_session.add(visit)
    await superadmin_session.commit()

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        decision = await eligibility_service.evaluate_and_persist(app_session, visit.visit_id)

    assert decision.status == EligibilityStatus.eligible
    assert decision.reason is None


@pytest.mark.asyncio
async def test_minor_is_suppressed(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    location: Location = base_setup["location"]  # type: ignore[assignment]
    department: Department = base_setup["department"]  # type: ignore[assignment]

    patient = _patient(account.account_id, b"\x02" * 32)
    superadmin_session.add(patient)
    await superadmin_session.commit()
    visit = _visit(
        account.account_id,
        location.location_id,
        department.department_id,
        patient.patient_ref_id,
        patient_age=10,
    )
    superadmin_session.add(visit)
    await superadmin_session.commit()

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        decision = await eligibility_service.evaluate_and_persist(app_session, visit.visit_id)

    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.minor

    # `visit` is already in superadmin_session's identity map from the add()+commit() above, so a
    # plain .get() would return that cached (pre-update) in-memory object rather than re-querying —
    # refresh() forces it to re-read the row app_session just updated.
    await superadmin_session.refresh(visit)
    assert visit.eligibility_status == EligibilityStatus.suppressed
    assert visit.suppression_reason == SuppressionReason.minor
    assert visit.eligibility_evaluated_at is not None


@pytest.mark.asyncio
async def test_opted_out_is_suppressed(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    location: Location = base_setup["location"]  # type: ignore[assignment]
    department: Department = base_setup["department"]  # type: ignore[assignment]

    phone_hash = b"\x03" * 32
    patient = _patient(account.account_id, phone_hash)
    superadmin_session.add(patient)
    await superadmin_session.commit()
    superadmin_session.add(
        SuppressionEntry(
            account_id=account.account_id,
            phone_hash=phone_hash,
            reason="opt_out",
            source="dashboard",
        )
    )
    await superadmin_session.commit()

    visit = _visit(
        account.account_id, location.location_id, department.department_id, patient.patient_ref_id
    )
    superadmin_session.add(visit)
    await superadmin_session.commit()

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        decision = await eligibility_service.evaluate_and_persist(app_session, visit.visit_id)

    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.opt_out


@pytest.mark.asyncio
async def test_frequency_cap_is_suppressed(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    location: Location = base_setup["location"]  # type: ignore[assignment]
    department: Department = base_setup["department"]  # type: ignore[assignment]

    patient = _patient(account.account_id, b"\x04" * 32)
    superadmin_session.add(patient)
    await superadmin_session.commit()

    # Outside the 7-day dedupe window (so rule 8 duplicate_encounter doesn't fire first) but still
    # inside the 30-day frequency_cap window (so rule 10 does) — isolates the rule under test from
    # rule 8, which precedes it and would otherwise win per doc 03 §1's ordering.
    older_visit = _visit(
        account.account_id,
        location.location_id,
        department.department_id,
        patient.patient_ref_id,
        visit_date=date.today() - timedelta(days=10),
    )
    superadmin_session.add(older_visit)
    await superadmin_session.commit()
    superadmin_session.add(
        Call(
            account_id=account.account_id,
            visit_id=older_visit.visit_id,
            attempt_no=1,
            scheduled_at=datetime.now(UTC) - timedelta(days=9),
            status=CallStatus.completed,
        )
    )
    await superadmin_session.commit()

    new_visit = _visit(
        account.account_id, location.location_id, department.department_id, patient.patient_ref_id
    )
    superadmin_session.add(new_visit)
    await superadmin_session.commit()

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        decision = await eligibility_service.evaluate_and_persist(app_session, new_visit.visit_id)

    assert decision.status == EligibilityStatus.suppressed
    assert decision.reason == SuppressionReason.frequency_cap


@pytest.mark.asyncio
async def test_shared_number_goes_to_review_then_resolve_review_audits(
    app_session: AsyncSession, superadmin_session: AsyncSession, base_setup: dict[str, object]
) -> None:
    account: Account = base_setup["account"]  # type: ignore[assignment]
    location: Location = base_setup["location"]  # type: ignore[assignment]
    department: Department = base_setup["department"]  # type: ignore[assignment]

    shared_phone_hash = b"\x05" * 32
    from app.core.ids import uuid7
    from app.db.models.ingestion import IngestionBatch

    batch = IngestionBatch(
        account_id=account.account_id, source="upload", filename="f.csv", sha256=uuid7().hex
    )
    superadmin_session.add(batch)
    await superadmin_session.commit()

    patients = [
        _patient(account.account_id, shared_phone_hash, external_patient_id=f"shared-{i}")
        for i in range(4)
    ]
    superadmin_session.add_all(patients)
    await superadmin_session.commit()

    visits = [
        _visit(
            account.account_id,
            location.location_id,
            department.department_id,
            p.patient_ref_id,
            batch_id=batch.batch_id,
        )
        for p in patients
    ]
    superadmin_session.add_all(visits)
    await superadmin_session.commit()

    target_visit = visits[0]
    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        decision = await eligibility_service.evaluate_and_persist(
            app_session, target_visit.visit_id
        )

    assert decision.status == EligibilityStatus.review
    assert decision.reason == SuppressionReason.shared_number_review

    reviewer = User(
        account_id=account.account_id, email="quality@example.com", name="Q", role=UserRole.quality
    )
    superadmin_session.add(reviewer)
    await superadmin_session.commit()

    async with app_session.begin():
        await set_account_scope(app_session, account.account_id)
        resolved = await eligibility_service.resolve_review(
            app_session,
            target_visit.visit_id,
            "eligible",
            "confirmed with patient",
            reviewer.user_id,
        )
        assert resolved.eligibility_status == EligibilityStatus.eligible

    audit_rows = list(
        (
            await superadmin_session.scalars(
                select(AuditLogEntry).where(AuditLogEntry.action == "visit.eligibility_review")
            )
        ).all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].entity_id == target_visit.visit_id
    assert audit_rows[0].after_json is not None
    assert audit_rows[0].after_json["note"] == "confirmed with patient"
