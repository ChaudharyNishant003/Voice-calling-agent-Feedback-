"""Demo MVP endpoints (spec §14, §21) — every route behind `require_demo_mode` (`api/deps.py`),
which 404s the instant `DEMO_MODE` is off. No login: this whole router is the confirmed "demo mode
without login" surface, kept structurally separate from every authenticated router.

Uses `get_superadmin_db_session` (BYPASSRLS), not the regular tenant-scoped session — deliberate,
not an oversight. The demo flow only ever touches one fixed, synthetic demo account; there's no
other tenant's data it could leak, and using the standard `set_account_scope` dance for a single-
tenant, no-login local demo would be pure boilerplate with no actual isolation benefit.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
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
from app.services import demo_conversation_service, demo_settings_service, provider_settings_service

# Real vendor adapter imports/construction live here, not in `services/` or `adapters/registry.py`
# — see that module's note for why (import-linter's transitive-reachability check on the "services
# never import vendor SDKs" contract). `app.api` isn't restricted by either contract.
router = APIRouter(
    prefix="/demo", tags=["demo"], dependencies=[Depends(require_demo_mode)]
)

_TEST_FNS = {"gemini": gemini_test_api_key, "openai": openai_test_api_key}

_MODEL_CHOICES = {
    "gemini": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"],
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


class SaveDemoSettingsRequest(BaseModel):
    hospital_name: str
    agent_name: str
    voice_gender: Literal["female", "male"]


class StartCallRequest(BaseModel):
    provider: Literal["gemini", "openai"]


class StartCallResponse(BaseModel):
    call_id: str
    greeting_text: str
    hospital_name: str
    agent_name: str
    voice_gender: str


class SubmitTurnRequest(BaseModel):
    provider: Literal["gemini", "openai"]
    text: str


class TurnResponse(BaseModel):
    response_text: str
    detected_language: str
    locked_language: str
    switched_language: bool
    topics: list[str]
    next_action: str
    end_call: bool
    summary: str | None


class TimelineEventResponse(BaseModel):
    event_id: int
    ts: str
    type: str
    data: dict[str, object]


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
        hospital_name=row.hospital_name, agent_name=row.agent_name, voice_gender=row.voice_gender
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
    )
    return DemoSettingsResponse(
        hospital_name=row.hospital_name, agent_name=row.agent_name, voice_gender=row.voice_gender
    )


@router.post("/calls")
async def start_call(
    body: StartCallRequest, session: AsyncSession = Depends(get_superadmin_db_session)
) -> StartCallResponse:
    result = await demo_conversation_service.start_call(session, provider=body.provider)
    return StartCallResponse(
        call_id=str(result.call_id),
        greeting_text=result.greeting_text,
        hospital_name=result.hospital_name,
        agent_name=result.agent_name,
        voice_gender=result.voice_gender,
    )


@router.post("/calls/{call_id}/turns")
async def submit_turn(
    call_id: UUID,
    body: SubmitTurnRequest,
    session: AsyncSession = Depends(get_superadmin_db_session),
) -> TurnResponse:
    registry = await _build_llm_registry(session, [body.provider])
    result = await demo_conversation_service.submit_turn(
        session, registry, call_id, body.provider, body.text
    )
    return TurnResponse(
        response_text=result.response_text,
        detected_language=result.detected_language,
        locked_language=result.locked_language,
        switched_language=result.switched_language,
        topics=result.topics,
        next_action=result.next_action,
        end_call=result.end_call,
        summary=result.summary,
    )


@router.post("/calls/{call_id}/end")
async def end_call(
    call_id: UUID, session: AsyncSession = Depends(get_superadmin_db_session)
) -> dict[str, str]:
    await demo_conversation_service.end_call(session, call_id)
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
