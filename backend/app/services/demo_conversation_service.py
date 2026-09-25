"""Demo MVP conversation engine orchestration (spec §11) — I/O + orchestration only; the actual
decision logic (language lock, topic tracking, end-of-call) is pure and lives in
`domain/conversation_language.py` / `domain/conversation_topics.py`.

Per-call engine state (locked language, streak counter, topics covered, turn count) is stored on
`Call.state_snapshot` (JSONB — already exists on the model, designed for exactly this) and
reconstructed each turn, since each HTTP request is a separate process invocation. Conversation
history is reconstructed from `Transcript` rows rather than duplicated elsewhere, so the debug
timeline and the LLM's own context always see the same data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pybreaker
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.interfaces import LLMAdapter
from app.adapters.registry import AdapterRegistry, call_with_breaker
from app.core.config import get_settings
from app.core.errors import AdapterError, NotFoundError
from app.core.errors import ValidationError as PFAValidationError
from app.core.ids import uuid7
from app.core.phone import phone_hash
from app.core.security import decrypt, encrypt, get_local_kek
from app.db.models.calls import Call, CallEvent, Transcript
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Account, Department, Location
from app.db.repositories.encryption_keys import get_or_create_dek
from app.domain.conversation_language import LanguageFamily, LanguageState, decide_language
from app.domain.conversation_topics import Topic, TopicState, record_topics, should_end
from app.domain.enums import (
    CallStatus,
    CampaignType,
    ConsentState,
    RespondentType,
    Speaker,
    VisitType,
)
from app.services import demo_settings_service
from app.services.demo_llm_schema import DemoTurnResponse
from app.services.demo_prompts import TurnContext, build_input_transcript, build_system_instruction

DEMO_ACCOUNT_NAME = "Demo Hospital"
DEMO_LOCATION_EXTERNAL_ID = "demo-location"
DEMO_DEPARTMENT_CODE = "demo-department"
DEMO_PHONE_E164 = "+919999999999"

_LLM_TIMEOUT_S = 20.0
_TRANSCRIPT_RETENTION_DAYS = 30
_FALLBACK_RESPONSE = "Sorry, thoda samajh nahi aaya. Kya aap dobara bata sakte hain?"

_DETECTED_TO_FAMILY = {
    "hi": LanguageFamily.hindi_hinglish,
    "hinglish": LanguageFamily.hindi_hinglish,
    "en": LanguageFamily.english,
}
_REQUESTED_TO_FAMILY = {"hi": LanguageFamily.hindi_hinglish, "en": LanguageFamily.english}


class DemoCallNotFoundError(NotFoundError):
    pass


class DemoCallAlreadyEndedError(PFAValidationError):
    pass


class DemoProviderNotConfiguredError(PFAValidationError):
    pass


@dataclass(frozen=True)
class DemoCallStarted:
    call_id: UUID
    greeting_text: str
    hospital_name: str
    agent_name: str
    voice_gender: str


@dataclass(frozen=True)
class AgentTurnResult:
    response_text: str
    detected_language: str
    locked_language: str
    switched_language: bool
    topics: list[str]
    next_action: str
    end_call: bool
    summary: str | None


@dataclass(frozen=True)
class CallEventOut:
    event_id: int
    ts: datetime
    type: str
    data: dict[str, object]


async def _get_or_create_demo_account(session: AsyncSession) -> Account:
    existing = await session.scalar(select(Account).where(Account.name == DEMO_ACCOUNT_NAME))
    if existing is not None:
        return existing
    account = Account(
        name=DEMO_ACCOUNT_NAME,
        display_name_tts=DEMO_ACCOUNT_NAME,
        caller_id_e164="+910000000000",
        retention_policy={"audio_days": 30, "transcript_days": 30, "verbatim_days": 30},
        sla_config={"p1": {"ack": 1, "resolve": 24}},
    )
    session.add(account)
    await session.flush()
    return account


async def _get_or_create_demo_location(session: AsyncSession, account_id: UUID) -> Location:
    existing = await session.scalar(
        select(Location).where(
            Location.account_id == account_id,
            Location.external_location_id == DEMO_LOCATION_EXTERNAL_ID,
        )
    )
    if existing is not None:
        return existing
    location = Location(
        account_id=account_id, external_location_id=DEMO_LOCATION_EXTERNAL_ID, name="Demo Campus"
    )
    session.add(location)
    await session.flush()
    return location


async def _get_or_create_demo_department(session: AsyncSession, account_id: UUID) -> Department:
    existing = await session.scalar(
        select(Department).where(
            Department.account_id == account_id, Department.code == DEMO_DEPARTMENT_CODE
        )
    )
    if existing is not None:
        return existing
    department = Department(
        account_id=account_id, code=DEMO_DEPARTMENT_CODE, name="Demo Department"
    )
    session.add(department)
    await session.flush()
    return department


async def _emit_event(
    session: AsyncSession, call_id: UUID, event_type: str, data: dict[str, object] | None = None
) -> None:
    session.add(CallEvent(call_id=call_id, type=event_type, data=data or {}))
    await session.flush()


async def _persist_transcript_turn(
    session: AsyncSession,
    call_id: UUID,
    account_id: UUID,
    speaker: str,
    text: str,
    turn_index: int,
) -> None:
    kek = get_local_kek()
    dek = await get_or_create_dek(session, account_id, kek=kek)
    session.add(
        Transcript(
            transcript_id=uuid7(),
            call_id=call_id,
            turn_index=turn_index,
            speaker=Speaker(speaker),
            text_enc=encrypt(text, dek),
            start_ms=0,
            end_ms=0,
            retention_until=datetime.now(UTC) + timedelta(days=_TRANSCRIPT_RETENTION_DAYS),
        )
    )
    await session.flush()


async def _load_history(session: AsyncSession, call: Call) -> list[tuple[str, str]]:
    rows = list(
        (
            await session.scalars(
                select(Transcript)
                .where(Transcript.call_id == call.call_id)
                .order_by(Transcript.turn_index)
            )
        ).all()
    )
    if not rows:
        return []
    kek = get_local_kek()
    dek = await get_or_create_dek(session, call.account_id, kek=kek)
    return [(row.speaker.value, decrypt(row.text_enc, dek)) for row in rows]


def _snapshot_int(snapshot: dict[str, object], key: str, default: int = 0) -> int:
    value = snapshot.get(key)
    return value if isinstance(value, int) else default


def _greeting_text(hospital_name: str, agent_name: str, voice_gender: str) -> str:
    verb = "bol rahi hoon" if voice_gender == "female" else "bol raha hoon"
    return (
        f"Namaste! Main {hospital_name} se {agent_name} {verb} — aapki recent visit ke baare mein "
        "ek quick feedback lena tha. Overall experience kaisa raha?"
    )


async def start_call(session: AsyncSession, *, provider: str) -> DemoCallStarted:
    account = await _get_or_create_demo_account(session)
    location = await _get_or_create_demo_location(session, account.account_id)
    department = await _get_or_create_demo_department(session, account.account_id)
    settings = await demo_settings_service.get_settings(session)

    kek = get_local_kek()
    dek = await get_or_create_dek(session, account.account_id, kek=kek)
    pepper = get_settings().phone_hash_pepper
    patient = Patient(
        patient_ref_id=uuid7(),
        account_id=account.account_id,
        external_patient_id=f"demo-{uuid7().hex}",
        phone_hash=bytes.fromhex(phone_hash(DEMO_PHONE_E164, pepper=pepper)),
        phone_e164_enc=encrypt(DEMO_PHONE_E164, dek),
        phone_last4=DEMO_PHONE_E164[-4:],
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        visit_id=uuid7(),
        account_id=account.account_id,
        location_id=location.location_id,
        patient_ref_id=patient.patient_ref_id,
        department_id=department.department_id,
        external_visit_key=f"demo-{uuid7().hex}",
        visit_date=datetime.now(UTC).date(),
        visit_type=VisitType.outpatient,
        patient_age=35,
    )
    session.add(visit)
    await session.flush()

    now = datetime.now(UTC)
    call = Call(
        call_id=uuid7(),
        account_id=account.account_id,
        visit_id=visit.visit_id,
        campaign_type=CampaignType.service_feedback,
        attempt_no=1,
        scheduled_at=now,
        started_at=now,
        answered_at=now,
        status=CallStatus.in_progress,
        # Demo-specific: role-played by the product owner, not a real patient, so the formal
        # recorded-consent gate (CLAUDE.md rule 4) doesn't apply the way it does in production —
        # `granted_unrecorded` says exactly that plainly rather than claiming a consent flow that
        # never ran.
        consent_state=ConsentState.granted_unrecorded,
        consent_at=now,
        respondent=RespondentType.patient,
        languages_used=[],
        turn_count=0,
    )
    session.add(call)
    await session.flush()

    await _emit_event(session, call.call_id, "CALL_STARTED", {"provider": provider})

    greeting = _greeting_text(settings.hospital_name, settings.agent_name, settings.voice_gender)
    await _persist_transcript_turn(session, call.call_id, account.account_id, "agent", greeting, 0)
    await _emit_event(session, call.call_id, "AGENT_GREETING", {"text": greeting})

    return DemoCallStarted(
        call_id=call.call_id,
        greeting_text=greeting,
        hospital_name=settings.hospital_name,
        agent_name=settings.agent_name,
        voice_gender=settings.voice_gender,
    )


async def _call_llm_with_retry(
    session: AsyncSession,
    call_id: UUID,
    registry: AdapterRegistry[LLMAdapter],
    provider: str,
    variables: dict[str, object],
    fallback_language: str,
) -> DemoTurnResponse:
    adapter = registry.get(provider)
    breaker = registry.breaker(provider)

    for attempt in (1, 2):
        try:
            result = await call_with_breaker(
                breaker, adapter.complete, "demo_feedback_turn", variables, timeout_s=_LLM_TIMEOUT_S
            )
            return DemoTurnResponse.model_validate(result.data)
        except pybreaker.CircuitBreakerError as exc:
            await _emit_event(
                session,
                call_id,
                "ERROR",
                {"attempt": attempt, "message": f"circuit breaker: {exc}"},
            )
        except AdapterError as exc:
            await _emit_event(
                session,
                call_id,
                "ERROR",
                {"attempt": attempt, "code": exc.code, "message": exc.message},
            )
        except PydanticValidationError as exc:
            await _emit_event(
                session,
                call_id,
                "ERROR",
                {"attempt": attempt, "message": f"malformed structured output: {exc}"},
            )

    await _emit_event(
        session, call_id, "ERROR", {"message": "LLM failed twice in a row; using fallback response"}
    )
    return DemoTurnResponse(
        response=_FALLBACK_RESPONSE,
        detected_language="hi" if fallback_language == "hindi_hinglish" else "en",
        next_action="follow_up",
        end_call=False,
    )


async def submit_turn(
    session: AsyncSession,
    registry: AdapterRegistry[LLMAdapter],
    call_id: UUID,
    provider: str,
    user_text: str,
) -> AgentTurnResult:
    call = await session.get(Call, call_id)
    if call is None:
        raise DemoCallNotFoundError("PFA-DEMO-006", message="Demo call not found.")
    if call.status != CallStatus.in_progress:
        raise DemoCallAlreadyEndedError("PFA-DEMO-007", message="This demo call has already ended.")
    if not registry.has(provider):
        # Checked here, before any persistence, rather than left to surface as a bare KeyError out
        # of `_call_llm_with_retry` — this is a setup problem (no connected key for this provider),
        # not a transient runtime failure, so it doesn't belong in that function's retry/fallback
        # path (spec §17: "missing key" must say exactly what to configure, not crash).
        raise DemoProviderNotConfiguredError(
            "PFA-DEMO-008",
            message=(
                f"{provider} isn't configured yet. Save and test a working API key for it in "
                "Settings, then try again."
            ),
        )

    settings = await demo_settings_service.get_settings(session)

    snapshot: dict[str, object] = call.state_snapshot or {}
    locked_raw = snapshot.get("locked_language")
    language_state = LanguageState(
        locked=LanguageFamily(locked_raw) if isinstance(locked_raw, str) else None,
        consecutive_other_count=_snapshot_int(snapshot, "consecutive_other_count"),
    )
    topics_raw = snapshot.get("topics_covered")
    topics_list = topics_raw if isinstance(topics_raw, list) else []
    topic_state = TopicState(
        covered=frozenset(Topic(t) for t in topics_list if isinstance(t, str))
    )
    turn_count = _snapshot_int(snapshot, "turn_count")

    history = await _load_history(session, call)
    next_index = len(history)
    await _persist_transcript_turn(
        session, call_id, call.account_id, "patient", user_text, next_index
    )
    await _emit_event(session, call_id, "USER_INPUT", {"length": len(user_text)})

    ctx = TurnContext(
        hospital_name=settings.hospital_name,
        agent_name=settings.agent_name,
        voice_gender=settings.voice_gender,
        locked_language=language_state.locked.value if language_state.locked else None,
        topics_covered=frozenset(t.value for t in topic_state.covered),
        turn_count=turn_count,
        history=history,
        latest_patient_input=user_text,
    )
    variables: dict[str, object] = {
        "system_instruction": build_system_instruction(ctx),
        "input_transcript": build_input_transcript(ctx),
    }

    await _emit_event(session, call_id, "LLM_REQUEST", {"provider": provider})
    fallback_lang = language_state.locked.value if language_state.locked else "hindi_hinglish"
    parsed = await _call_llm_with_retry(
        session, call_id, registry, provider, variables, fallback_lang
    )
    await _emit_event(
        session,
        call_id,
        "LLM_RESPONSE",
        {"next_action": parsed.next_action, "end_call": parsed.end_call},
    )

    detected_family = _DETECTED_TO_FAMILY[parsed.detected_language]
    requested_family = (
        _REQUESTED_TO_FAMILY.get(parsed.requested_language) if parsed.requested_language else None
    )
    decision = decide_language(language_state, detected_family, requested=requested_family)
    await _emit_event(
        session,
        call_id,
        "LANGUAGE_DETECTED",
        {"detected": parsed.detected_language, "requested": parsed.requested_language},
    )
    if decision.switched:
        locked_value = decision.state.locked.value if decision.state.locked else None
        await _emit_event(session, call_id, "LANGUAGE_SWITCHED", {"new_locked": locked_value})

    new_topic_state = record_topics(topic_state, frozenset(Topic(t) for t in parsed.topics))
    new_turn_count = turn_count + 1
    ends = should_end(turn_count=new_turn_count, llm_wants_to_end=parsed.end_call)

    await _persist_transcript_turn(
        session, call_id, call.account_id, "agent", parsed.response, next_index + 1
    )
    event_type = "FOLLOWUP" if parsed.next_action == "follow_up" else "AGENT_RESPONSE"
    await _emit_event(session, call_id, event_type, {"text": parsed.response})

    locked_value = decision.state.locked.value if decision.state.locked else None
    call.state_snapshot = {
        "locked_language": locked_value,
        "consecutive_other_count": decision.state.consecutive_other_count,
        "topics_covered": sorted(t.value for t in new_topic_state.covered),
        "turn_count": new_turn_count,
    }
    call.turn_count = new_turn_count
    if locked_value and locked_value not in (call.languages_used or []):
        call.languages_used = [*(call.languages_used or []), locked_value]

    if ends:
        call.status = CallStatus.completed
        call.ended_at = datetime.now(UTC)
        call.end_reason = "feedback_collected"
        await _emit_event(session, call_id, "CALL_ENDED", {"summary": parsed.summary})

    await session.flush()

    return AgentTurnResult(
        response_text=parsed.response,
        detected_language=parsed.detected_language,
        locked_language=locked_value or "",
        switched_language=decision.switched,
        topics=sorted(t.value for t in new_topic_state.covered),
        next_action=parsed.next_action,
        end_call=ends,
        summary=parsed.summary,
    )


async def end_call(session: AsyncSession, call_id: UUID) -> None:
    call = await session.get(Call, call_id)
    if call is None:
        raise DemoCallNotFoundError("PFA-DEMO-006", message="Demo call not found.")
    if call.status == CallStatus.in_progress:
        call.status = CallStatus.completed
        call.ended_at = datetime.now(UTC)
        call.end_reason = "manually_ended"
        await _emit_event(session, call_id, "CALL_ENDED", {"reason": "manually_ended"})
        await session.flush()


async def get_timeline(session: AsyncSession, call_id: UUID) -> list[CallEventOut]:
    call = await session.get(Call, call_id)
    if call is None:
        raise DemoCallNotFoundError("PFA-DEMO-006", message="Demo call not found.")
    rows = list(
        (
            await session.scalars(
                select(CallEvent)
                .where(CallEvent.call_id == call_id)
                .order_by(CallEvent.ts, CallEvent.id)
            )
        ).all()
    )
    return [CallEventOut(event_id=r.id, ts=r.ts, type=r.type, data=r.data) for r in rows]
