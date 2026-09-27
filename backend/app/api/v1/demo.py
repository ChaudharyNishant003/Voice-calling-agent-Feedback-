"""Demo MVP endpoints (spec §14, §21) — every route behind `require_demo_mode` (`api/deps.py`),
which 404s the instant `DEMO_MODE` is off. No login: this whole router is the confirmed "demo mode
without login" surface, kept structurally separate from every authenticated router.

Uses `get_superadmin_db_session` (BYPASSRLS), not the regular tenant-scoped session — deliberate,
not an oversight. The demo flow only ever touches one fixed, synthetic demo account; there's no
other tenant's data it could leak, and using the standard `set_account_scope` dance for a single-
tenant, no-login local demo would be pure boilerplate with no actual isolation benefit.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.gemini.llm import GeminiLLM
from app.adapters.gemini.llm import test_api_key as gemini_test_api_key
from app.adapters.interfaces import LLMAdapter
from app.adapters.openai.llm import OpenAILLM
from app.adapters.openai.llm import test_api_key as openai_test_api_key
from app.adapters.registry import AdapterRegistry
from app.api.deps import get_superadmin_db_session, require_demo_mode
from app.core.errors import AdapterAuthError, AdapterError
from app.services import (
    demo_conversation_service,
    demo_playground_service,
    demo_settings_service,
    pfa_call_service,
    pfa_results_service,
    provider_settings_service,
)
from app.services.demo_conversation_service import DemoProviderNotConfiguredError

# Real vendor adapter imports/construction live here, not in `services/` or `adapters/registry.py`
# — see that module's note for why (import-linter's transitive-reachability check on the "services
# never import vendor SDKs" contract). `app.api` isn't restricted by either contract.
router = APIRouter(
    prefix="/demo", tags=["demo"], dependencies=[Depends(require_demo_mode)]
)

_TEST_FNS = {"gemini": gemini_test_api_key, "openai": openai_test_api_key}

_MODEL_CHOICES = {
    # gemini-3.5-flash-lite listed first (and the recommended default): verified by hand to
    # respond in ~4-5s with its own separate free-tier quota, vs. gemini-3.8-flash's free tier
    # (20 requests/day, shared with nothing else) which a single demo session exhausts quickly and
    # then hangs for 2-3 minutes before failing (docs/11_BUILD_PLAN.md's Demo MVP section).
    # gemini-2.5-flash removed entirely — confirmed dead for new API keys (404 "no longer available
    # to new users"), so offering it would just be a guaranteed-broken choice in the dropdown.
    "gemini": ["gemini-3.5-flash-lite", "gemini-3.8-flash"],
    "openai": ["gpt-6-sol", "gpt-6-luna", "gpt-6-astra"],
}


class ProviderStatusResponse(BaseModel):
    provider: str
    status: str
    model: str | None
    tested_at: str | None
    available_models: list[str]


class SaveProviderKeyRequest(BaseModel):
    api_key: str
    model: str


class DemoSettingsResponse(BaseModel):
    hospital_name: str
    agent_name: str
    voice_gender: str
    hospital_phone: str | None
    escalation_sla_text: str | None
    tts_script: str


class SaveDemoSettingsRequest(BaseModel):
    hospital_name: str
    agent_name: str
    voice_gender: Literal["female", "male"]
    hospital_phone: str | None = None
    escalation_sla_text: str | None = None
    tts_script: Literal["devanagari", "roman"] = "devanagari"


class StartCallRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    patient_first_name: str
    patient_phone: str | None = None
    visit_type: Literal["OPD", "IPD", "DIAGNOSTICS", "EMERGENCY"]
    visit_date: date
    department: str | None = None
    doctor_name: str | None = None
    patient_age: int | None = None


class StartCallFromVisitRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    patient_first_name: str | None = None


class ConversationTurnResponse(BaseModel):
    call_id: str
    display_text: str
    speech_text: str
    speech_lang: str
    node: str
    ended: bool
    call_outcome: str | None
    escalated: bool


class SubmitTurnRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    type: Literal["utterance", "silence", "stt_error"] = "utterance"
    text: str | None = None


class ResultListItemResponse(BaseModel):
    call_id: str
    visit_id: str
    started_at: str | None
    ended_at: str | None
    patient_first_name: str | None
    visit_type: str
    department: str | None
    outcome: str | None
    rating: int | None
    severity_max: str | None
    complaint_count: int
    escalated: bool


class ResultsPageResponse(BaseModel):
    items: list[ResultListItemResponse]
    total: int


class ResultDetailResponse(BaseModel):
    call_id: str
    patient_first_name: str | None
    visit_type: str
    visit_date: str
    department: str | None
    doctor_name: str | None
    outcome: str | None
    respondent_type: str
    language_mode: str | None
    rating: int | None
    rating_inferred: bool
    topics: list[dict[str, object]]
    complaints: list[dict[str, object]]
    escalations: list[dict[str, object]]
    transcript: list[dict[str, str]]


class EscalationResponse(BaseModel):
    id: str
    call_id: str
    type: str
    category: str
    triggered_by: str
    status: str
    created_at: str
    acknowledged_at: str | None


class TimelineEventResponse(BaseModel):
    event_id: int
    ts: str
    type: str
    data: dict[str, object]


class PlaygroundLanguageDetectionRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    model: str
    patient_text: str


class PlaygroundLanguageDetectionResponse(BaseModel):
    detected_language: str
    requested_language: str | None
    raw_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str


class PlaygroundTopicExtractionRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    model: str
    patient_text: str


class PlaygroundTopicExtractionResponse(BaseModel):
    topics: list[str]
    raw_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str


class PlaygroundLanguageLockRequest(BaseModel):
    detected_language: str
    requested_language: str | None = None
    prior_locked_language: str | None = None
    prior_streak: int = 0


class PlaygroundLanguageLockResponse(BaseModel):
    locked_language: str | None
    consecutive_other_count: int
    switched: bool


class PlaygroundTopicTrackingRequest(BaseModel):
    topics_mentioned: list[str]
    prior_topics_covered: list[str] = []


class PlaygroundTopicTrackingResponse(BaseModel):
    topics_covered: list[str]


class PlaygroundEndJudgmentRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    model: str
    patient_text: str
    topics_covered: list[str] = []
    turn_count: int


class PlaygroundEndJudgmentResponse(BaseModel):
    wants_to_end: bool
    summary: str | None
    raw_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str


class PlaygroundEndCeilingRequest(BaseModel):
    turn_count: int
    llm_wants_to_end: bool


class PlaygroundEndCeilingResponse(BaseModel):
    ends: bool


class PlaygroundResponseGenerationRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    model: str
    patient_text: str
    locked_language: str | None = None
    topics_covered: list[str] = []
    is_ending: bool = False


class PlaygroundResponseGenerationResponse(BaseModel):
    response: str
    next_action: str
    raw_text: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str


async def _build_llm_registry(
    session: AsyncSession, providers: list[Literal["gemini", "openai"]]
) -> AdapterRegistry[LLMAdapter]:
    credentials = await provider_settings_service.get_decrypted_credentials(session, providers)
    registry = AdapterRegistry[LLMAdapter]()
    if "gemini" in credentials:
        api_key, model = credentials["gemini"]
        registry.register("gemini", GeminiLLM(api_key=api_key, model=model))
    if "openai" in credentials:
        api_key, model = credentials["openai"]
        registry.register("openai", OpenAILLM(api_key=api_key, model=model))
    return registry


async def _build_single_adapter(
    session: AsyncSession, provider: Literal["gemini", "openai"], model: str
) -> LLMAdapter:
    """Playground variant of `_build_llm_registry`: same saved, decrypted key, but the *requested*
    model rather than whatever's saved as the default — comparing models is the entire point, so
    the Playground is never limited to the one model Settings happens to have saved.
    """
    credentials = await provider_settings_service.get_decrypted_credentials(session, [provider])
    if provider not in credentials:
        raise DemoProviderNotConfiguredError(
            "PFA-DEMO-008",
            message=(
                f"{provider} isn't configured yet. Save and test a working API key for it in "
                "Settings, then try again."
            ),
        )
    api_key, _saved_model = credentials[provider]
    if provider == "gemini":
        return GeminiLLM(api_key=api_key, model=model)
    return OpenAILLM(api_key=api_key, model=model)


@router.get("/providers")
async def list_providers(
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> list[ProviderStatusResponse]:
    rows = await provider_settings_service.list_status(session)
    by_provider = {row.provider: row for row in rows}
    out = []
    for provider, models in _MODEL_CHOICES.items():
        row = by_provider.get(provider)
        out.append(
            ProviderStatusResponse(
                provider=provider,
                status=row.status if row else "not_configured",
                model=row.model if row else None,
                tested_at=row.tested_at.isoformat() if row and row.tested_at else None,
                available_models=models,
            )
        )
    return out


@router.post("/providers/{provider}/key")
async def save_provider_key(
    provider: Literal["gemini", "openai"],
    body: SaveProviderKeyRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> ProviderStatusResponse:
    try:
        await _TEST_FNS[provider](body.api_key, body.model)
        status: Literal["connected", "invalid", "error"] = "connected"
    except AdapterAuthError:
        status = "invalid"
    except AdapterError:
        status = "error"

    row = await provider_settings_service.save_key(
        session, provider, body.api_key, body.model, status
    )
    return ProviderStatusResponse(
        provider=row.provider,
        status=row.status,
        model=row.model,
        tested_at=row.tested_at.isoformat() if row.tested_at else None,
        available_models=_MODEL_CHOICES[provider],
    )


@router.get("/settings")
async def get_demo_settings(
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> DemoSettingsResponse:
    row = await demo_settings_service.get_settings(session)
    return DemoSettingsResponse(
        hospital_name=row.hospital_name,
        agent_name=row.agent_name,
        voice_gender=row.voice_gender,
        hospital_phone=row.hospital_phone,
        escalation_sla_text=row.escalation_sla_text,
        tts_script=row.tts_script,
    )


@router.put("/settings")
async def save_demo_settings(
    body: SaveDemoSettingsRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> DemoSettingsResponse:
    row = await demo_settings_service.save_settings(
        session,
        hospital_name=body.hospital_name,
        agent_name=body.agent_name,
        voice_gender=body.voice_gender,
        hospital_phone=body.hospital_phone,
        escalation_sla_text=body.escalation_sla_text,
        tts_script=body.tts_script,
    )
    return DemoSettingsResponse(
        hospital_name=row.hospital_name,
        agent_name=row.agent_name,
        voice_gender=row.voice_gender,
        hospital_phone=row.hospital_phone,
        escalation_sla_text=row.escalation_sla_text,
        tts_script=row.tts_script,
    )


@router.post("/calls")
async def start_call(
    body: StartCallRequest, session: AsyncSession = Depends(get_superadmin_db_session)
) -> ConversationTurnResponse:
    result = await pfa_call_service.start_call(
        session,
        pfa_call_service.StartCallInput(
            provider=body.provider,
            patient_first_name=body.patient_first_name,
            patient_phone=body.patient_phone,
            visit_type=body.visit_type,
            visit_date=body.visit_date,
            department=body.department,
            doctor_name=body.doctor_name,
            patient_age=body.patient_age,
        ),
    )
    return ConversationTurnResponse(
        call_id=str(result.call_id),
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=result.node,
        ended=result.ended,
        call_outcome=result.call_outcome,
        escalated=result.escalated,
    )


@router.post("/calls/from-visit/{visit_id}")
async def start_call_from_visit(
    visit_id: UUID,
    body: StartCallFromVisitRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> ConversationTurnResponse:
    """PRD v2 Phase 8: start a demo call from a visit that already exists via the existing S1.6
    CSV ingestion, instead of the patient/visit form `start_call` above uses.
    """
    result = await pfa_call_service.start_call_from_visit(
        session,
        visit_id=visit_id,
        provider=body.provider,
        patient_first_name=body.patient_first_name,
    )
    return ConversationTurnResponse(
        call_id=str(result.call_id),
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=result.node,
        ended=result.ended,
        call_outcome=result.call_outcome,
        escalated=result.escalated,
    )


@router.post("/calls/{call_id}/turns")
async def submit_turn(
    call_id: UUID,
    body: SubmitTurnRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> ConversationTurnResponse:
    registry = await _build_llm_registry(session, [body.provider])
    result = await pfa_call_service.submit_turn(
        session, registry, call_id, body.provider, body.type, body.text
    )
    return ConversationTurnResponse(
        call_id=str(result.call_id),
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=result.node,
        ended=result.ended,
        call_outcome=result.call_outcome,
        escalated=result.escalated,
    )


@router.post("/calls/{call_id}/end")
async def end_call(
    call_id: UUID, session: AsyncSession = Depends(get_superadmin_db_session)
) -> dict[str, str]:
    await pfa_call_service.end_call(session, call_id)
    return {"status": "ended"}


@router.get("/calls/{call_id}/events")
async def get_call_events(
    call_id: UUID, session: AsyncSession = Depends(get_superadmin_db_session)
) -> list[TimelineEventResponse]:
    events = await demo_conversation_service.get_timeline(session, call_id)
    return [
        TimelineEventResponse(event_id=e.event_id, ts=e.ts.isoformat(), type=e.type, data=e.data)
        for e in events
    ]


@router.get("/results")
async def list_results(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> ResultsPageResponse:
    page = await pfa_results_service.list_results(session, limit=limit, offset=offset)
    return ResultsPageResponse(
        items=[
            ResultListItemResponse(
                call_id=str(r.call_id),
                visit_id=str(r.visit_id),
                started_at=r.started_at.isoformat() if r.started_at else None,
                ended_at=r.ended_at.isoformat() if r.ended_at else None,
                patient_first_name=r.patient_first_name,
                visit_type=r.visit_type,
                department=r.department,
                outcome=r.outcome,
                rating=r.rating,
                severity_max=r.severity_max,
                complaint_count=r.complaint_count,
                escalated=r.escalated,
            )
            for r in page.items
        ],
        total=page.total,
    )


@router.get("/results/export.csv")
async def export_results_csv(
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> StreamingResponse:
    import csv
    import io

    page = await pfa_results_service.list_results(session, limit=None)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "call_id", "visit_id", "started_at", "ended_at", "patient_first_name", "visit_type",
            "department", "outcome", "rating", "severity_max", "complaint_count", "escalated",
        ]
    )
    for r in page.items:
        writer.writerow(
            [
                str(r.call_id),
                str(r.visit_id),
                r.started_at.isoformat() if r.started_at else "",
                r.ended_at.isoformat() if r.ended_at else "",
                r.patient_first_name or "",
                r.visit_type,
                r.department or "",
                r.outcome or "",
                r.rating if r.rating is not None else "",
                r.severity_max or "",
                r.complaint_count,
                r.escalated,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=demo_results.csv"},
    )


@router.get("/results/{call_id}")
async def get_result_detail(
    call_id: UUID, session: AsyncSession = Depends(get_superadmin_db_session)
) -> ResultDetailResponse:
    detail = await pfa_results_service.get_result_detail(session, call_id)
    return ResultDetailResponse(
        call_id=str(detail.call_id),
        patient_first_name=detail.patient_first_name,
        visit_type=detail.visit_type,
        visit_date=detail.visit_date,
        department=detail.department,
        doctor_name=detail.doctor_name,
        outcome=detail.outcome,
        respondent_type=detail.respondent_type,
        language_mode=detail.language_mode,
        rating=detail.rating,
        rating_inferred=detail.rating_inferred,
        topics=detail.topics,
        complaints=detail.complaints,
        escalations=detail.escalations,
        transcript=[{"speaker": s, "text": t} for s, t in detail.transcript],
    )


@router.get("/escalations")
async def list_escalations(
    status: Literal["open", "acknowledged", "closed"] | None = None,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> list[EscalationResponse]:
    rows = await pfa_results_service.list_escalations(session, status=status)
    return [
        EscalationResponse(
            id=str(e.id),
            call_id=str(e.call_id),
            type=e.type,
            category=e.category,
            triggered_by=e.triggered_by,
            status=e.status,
            created_at=e.created_at.isoformat(),
            acknowledged_at=e.acknowledged_at.isoformat() if e.acknowledged_at else None,
        )
        for e in rows
    ]


@router.post("/escalations/{escalation_id}/ack")
async def acknowledge_escalation(
    escalation_id: UUID, session: AsyncSession = Depends(get_superadmin_db_session)
) -> EscalationResponse:
    e = await pfa_results_service.acknowledge_escalation(session, escalation_id)
    return EscalationResponse(
        id=str(e.id),
        call_id=str(e.call_id),
        type=e.type,
        category=e.category,
        triggered_by=e.triggered_by,
        status=e.status,
        created_at=e.created_at.isoformat(),
        acknowledged_at=e.acknowledged_at.isoformat() if e.acknowledged_at else None,
    )


# --- Playground: manual, per-stage, per-model pipeline inspection (docs/11_BUILD_PLAN.md's Demo
# MVP section). Stateless — no Call/Transcript/CallEvent rows are written by any of these routes,
# and nothing here changes what the live /demo call above actually uses.


@router.post("/playground/steps/language-detection")
async def playground_language_detection(
    body: PlaygroundLanguageDetectionRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> PlaygroundLanguageDetectionResponse:
    adapter = await _build_single_adapter(session, body.provider, body.model)
    outcome = await demo_playground_service.run_language_detection(
        adapter, patient_text=body.patient_text
    )
    return PlaygroundLanguageDetectionResponse(
        detected_language=outcome.parsed.detected_language,
        requested_language=outcome.parsed.requested_language,
        raw_text=outcome.raw_text,
        latency_ms=outcome.latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        model=outcome.model,
    )


@router.post("/playground/steps/topic-extraction")
async def playground_topic_extraction(
    body: PlaygroundTopicExtractionRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> PlaygroundTopicExtractionResponse:
    adapter = await _build_single_adapter(session, body.provider, body.model)
    outcome = await demo_playground_service.run_topic_extraction(
        adapter, patient_text=body.patient_text
    )
    return PlaygroundTopicExtractionResponse(
        topics=outcome.parsed.topics,
        raw_text=outcome.raw_text,
        latency_ms=outcome.latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        model=outcome.model,
    )


@router.post("/playground/steps/language-lock")
async def playground_language_lock(
    body: PlaygroundLanguageLockRequest,
) -> PlaygroundLanguageLockResponse:
    outcome = demo_playground_service.run_language_lock(
        detected_language=body.detected_language,
        requested_language=body.requested_language,
        prior_locked_language=body.prior_locked_language,
        prior_streak=body.prior_streak,
    )
    return PlaygroundLanguageLockResponse(
        locked_language=outcome.locked_language,
        consecutive_other_count=outcome.consecutive_other_count,
        switched=outcome.switched,
    )


@router.post("/playground/steps/topic-tracking")
async def playground_topic_tracking(
    body: PlaygroundTopicTrackingRequest,
) -> PlaygroundTopicTrackingResponse:
    outcome = demo_playground_service.run_topic_tracking(
        topics_mentioned=body.topics_mentioned, prior_topics_covered=body.prior_topics_covered
    )
    return PlaygroundTopicTrackingResponse(topics_covered=outcome.topics_covered)


@router.post("/playground/steps/end-judgment")
async def playground_end_judgment(
    body: PlaygroundEndJudgmentRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> PlaygroundEndJudgmentResponse:
    adapter = await _build_single_adapter(session, body.provider, body.model)
    outcome = await demo_playground_service.run_end_judgment(
        adapter,
        patient_text=body.patient_text,
        topics_covered=frozenset(body.topics_covered),
        turn_count=body.turn_count,
    )
    return PlaygroundEndJudgmentResponse(
        wants_to_end=outcome.parsed.wants_to_end,
        summary=outcome.parsed.summary,
        raw_text=outcome.raw_text,
        latency_ms=outcome.latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        model=outcome.model,
    )


@router.post("/playground/steps/end-ceiling")
async def playground_end_ceiling(
    body: PlaygroundEndCeilingRequest,
) -> PlaygroundEndCeilingResponse:
    ends = demo_playground_service.run_end_ceiling(
        turn_count=body.turn_count, llm_wants_to_end=body.llm_wants_to_end
    )
    return PlaygroundEndCeilingResponse(ends=ends)


@router.post("/playground/steps/response-generation")
async def playground_response_generation(
    body: PlaygroundResponseGenerationRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> PlaygroundResponseGenerationResponse:
    adapter = await _build_single_adapter(session, body.provider, body.model)
    settings = await demo_settings_service.get_settings(session)
    outcome = await demo_playground_service.run_response_generation(
        adapter,
        hospital_name=settings.hospital_name,
        agent_name=settings.agent_name,
        voice_gender=settings.voice_gender,
        locked_language=body.locked_language,
        topics_covered=frozenset(body.topics_covered),
        is_ending=body.is_ending,
        patient_text=body.patient_text,
    )
    return PlaygroundResponseGenerationResponse(
        response=outcome.parsed.response,
        next_action=outcome.parsed.next_action,
        raw_text=outcome.raw_text,
        latency_ms=outcome.latency_ms,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        model=outcome.model,
    )
