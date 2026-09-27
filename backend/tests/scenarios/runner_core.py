"""Shared "drive one scenario through the real engine" logic (PRD v2 Phase 7), used by both the
mock-mode pytest module (`tests/integration/test_scenario_harness.py`) and the real-API CLI runner
(`runner.py`). Talks only to `pfa_call_service`/`pfa_results_service` — never re-implements engine
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.interfaces import LLMAdapter
from app.adapters.registry import AdapterRegistry
from app.services import pfa_call_service as svc
from app.services import pfa_results_service as results_svc
from tests.scenarios.assertions import check_expectations
from tests.scenarios.models import Scenario

MAX_TURNS_SAFETY_STOP = 30  # a scenario that never ends is an authoring bug, not a hang


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    passed: bool
    failures: tuple[str, ...]
    turns_taken: int
    error: str | None = None


def _start_input(scenario: Scenario) -> svc.StartCallInput:
    v = scenario.visit
    return svc.StartCallInput(
        provider="gemini",
        patient_first_name=v.patient_first_name,
        patient_phone=v.patient_phone,
        visit_type=v.visit_type,
        visit_date=date(2026, 9, 20),
        department=v.department,
        doctor_name=v.doctor_name,
        patient_age=v.patient_age,
    )


async def drive_scenario(
    session: AsyncSession,
    registry: AdapterRegistry[LLMAdapter],
    scenario: Scenario,
    *,
    provider: str = "gemini",
) -> ScenarioRunResult:
    try:
        started = await svc.start_call(session, _start_input(scenario))
        last = started
        turns_taken = 0
        for turn in scenario.turns:
            if last.ended:
                break
            last = await svc.submit_turn(
                session, registry, started.call_id, provider, turn.event_kind, turn.patient_text
            )
            turns_taken += 1
            if turns_taken > MAX_TURNS_SAFETY_STOP:
                return ScenarioRunResult(
                    scenario_id=scenario.id,
                    passed=False,
                    failures=(),
                    turns_taken=turns_taken,
                    error=f"exceeded {MAX_TURNS_SAFETY_STOP} turns without ending — likely a "
                    "scenario/engine loop, not a slow-but-real conversation",
                )
        if not last.ended:
            await svc.end_call(session, started.call_id)

        detail = await results_svc.get_result_detail(session, started.call_id)
        failures = tuple(
            check_expectations(expect=scenario.expect, last_result=last, detail=detail)
        )
        return ScenarioRunResult(
            scenario_id=scenario.id, passed=not failures, failures=failures, turns_taken=turns_taken
        )
    except Exception as exc:  # noqa: BLE001 - a scenario's own failure is data, not a harness crash
        return ScenarioRunResult(
            scenario_id=scenario.id, passed=False, failures=(), turns_taken=0, error=repr(exc)
        )
