"""No plaintext phone numbers or transcript text ever reach the DB (docs/08_TESTING_STRATEGY.md §6,
docs/07_SECURITY_AND_COMPLIANCE.md §3). Inserts real data through the actual encryption helpers,
then scans the raw columns — this is the DB-scan test S1.2's "Done when" refers to.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import normalize_e164, phone_hash
from app.core.security import encrypt, generate_dek
from app.db.models.calls import Call, Transcript
from app.db.models.enums import Speaker, VisitType
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account, Department, Location
from app.db.repositories.encryption_keys import get_or_create_dek
from app.db.session import set_account_scope

_DIGIT_RUN_RE = re.compile(r"\d{7,}")  # phone-shaped: 7+ consecutive digits
_PEPPER = "test-pepper-not-for-prod"
_KEK = generate_dek()  # test-only KEK; production loads this from KMS/settings


@pytest.mark.asyncio
async def test_patient_and_transcript_have_no_plaintext_phone_or_text(
    app_session: AsyncSession, superadmin_session: AsyncSession
) -> None:
    account = Account(
        name="Encryption Test Hospital",
        display_name_tts="Encryption Test Hospital",
        caller_id_e164="+911234567890",
        retention_policy={"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        sla_config={"p1": {"ack": 1, "resolve": 24}},
    )
    superadmin_session.add(account)
    await superadmin_session.commit()

    location = Location(
        account_id=account.account_id, external_location_id="loc-1", name="Main Campus"
    )
    department = Department(account_id=account.account_id, code="cardiology", name="Cardiology")
    superadmin_session.add_all([location, department])
    await superadmin_session.commit()

    raw_phone = "+919876543210"
    raw_transcript_text = (
        "The billing counter made me wait ninety minutes and nobody explained why."
    )

    await app_session.begin()
    await set_account_scope(app_session, account.account_id)

    dek = await get_or_create_dek(app_session, account.account_id, kek=_KEK)
    e164 = normalize_e164(raw_phone)

    patient = Patient(
        account_id=account.account_id,
        external_patient_id="ext-pat-1",
        phone_hash=bytes.fromhex(phone_hash(e164, pepper=_PEPPER)),
        phone_e164_enc=encrypt(e164, dek),
        phone_last4=e164[-4:],
    )
    app_session.add(patient)
    await app_session.flush()

    visit = Visit(
        account_id=account.account_id,
        location_id=location.location_id,
        patient_ref_id=patient.patient_ref_id,
        external_visit_key="visit-key-1",
        visit_date=date.today(),
        visit_type=VisitType.outpatient,
        department_id=department.department_id,
        patient_age=45,
    )
    app_session.add(visit)
    await app_session.flush()

    call = Call(
        account_id=account.account_id,
        visit_id=visit.visit_id,
        attempt_no=1,
        scheduled_at=datetime.now(UTC),
    )
    app_session.add(call)
    await app_session.flush()

    transcript = Transcript(
        call_id=call.call_id,
        turn_index=0,
        speaker=Speaker.patient,
        text_enc=encrypt(raw_transcript_text, dek),
        start_ms=0,
        end_ms=4200,
        retention_until=datetime.now(UTC) + timedelta(days=180),
    )
    app_session.add(transcript)
    await app_session.commit()

    # Scan the raw columns as text — encrypted bytea columns must not contain the plaintext, and
    # must not contain any long digit run (a phone number) once rendered.
    patients_row = (
        await app_session.execute(
            text(
                "SELECT encode(phone_e164_enc, 'escape') AS enc, phone_last4 FROM patients "
                "WHERE patient_ref_id = :id"
            ),
            {"id": patient.patient_ref_id},
        )
    ).one()
    transcripts_row = (
        await app_session.execute(
            text(
                "SELECT encode(text_enc, 'escape') AS enc FROM transcripts "
                "WHERE transcript_id = :id"
            ),
            {"id": transcript.transcript_id},
        )
    ).one()
    await app_session.commit()

    assert raw_phone not in patients_row.enc
    assert e164 not in patients_row.enc
    assert not _DIGIT_RUN_RE.search(patients_row.enc)
    # phone_last4 is deliberately visible for UI display (doc 02 §2) — not a leak.
    assert patients_row.phone_last4 == e164[-4:]

    assert raw_transcript_text not in transcripts_row.enc
