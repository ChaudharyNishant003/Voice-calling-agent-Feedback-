"""Runs every `tests/scenarios/cases/*.yaml` scenario in `--mock-llm` mode against a real Postgres
(PRD v2 Phase 7). This is the CI-safe half of the harness: deterministic canned LLM responses,
purely checking that every declared node-graph path/safety category/repair pattern still produces
the expected outcome, rating, complaint/escalation counts and severity. The other half — a small
sample driven by the real Gemini API with an LLM-simulated patient and an LLM judge — is
`tests/scenarios/runner.py`, run manually (not part of the default suite, since it costs real API
calls and isn't hermetic).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.registry import AdapterRegistry
from tests.scenarios.mock_llm import ScenarioLLM
from tests.scenarios.models import Scenario, load_scenarios
from tests.scenarios.runner_core import drive_scenario

_SCENARIOS = load_scenarios()


def _registry(llm: ScenarioLLM) -> AdapterRegistry:  # type: ignore[type-arg]
    registry = AdapterRegistry()  # type: ignore[var-annotated]
    registry.register("gemini", llm)
    return registry


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.id for s in _SCENARIOS])
async def test_scenario(scenario: Scenario, superadmin_session: AsyncSession) -> None:
    contracts = [t.contract for t in scenario.turns if t.contract is not None]
    llm = ScenarioLLM(contracts)
    registry = _registry(llm)

    result = await drive_scenario(superadmin_session, registry, scenario)

    assert result.error is None, f"{scenario.id} ({scenario.title}): harness error: {result.error}"
    assert result.passed, f"{scenario.id} ({scenario.title}): {'; '.join(result.failures)}"


def test_every_scenario_file_has_a_unique_id() -> None:
    ids = [s.id for s in _SCENARIOS]
    assert len(ids) == len(set(ids)), "duplicate scenario ids in tests/scenarios/cases/"
    assert len(_SCENARIOS) >= 40, f"expected at least 40 scenarios, found {len(_SCENARIOS)}"
