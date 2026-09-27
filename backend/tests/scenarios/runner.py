"""Real-API scenario sample runner (PRD v2 Phase 7). Drives one or more `cases/*.yaml` scenarios
through the *real* Gemini adapter — every node-LLM call this makes is a genuine API call, using the
same registered provider credentials the dashboard's Settings page saves — instead of the mock-mode
pytest module's canned `ScenarioLLM`.

**Scope decision vs. the original PRD wording** ("LLM-simulated patient + LLM judge, temperature
0.7/0 respectively"): this runner reuses each scenario's own scripted `turns[].patient_text` (the
same realistic Hindi/Hinglish/English utterances used in mock mode) rather than adding a second,
free-running patient-simulator LLM and a separate judge LLM. Reasoning: (1) a simulated patient
would need its own prompt/schema registered in `app/adapters/gemini/llm.py`'s `_PROMPT_SCHEMAS`,
which is app code — putting a test-harness-only concern there blurs the adapter-only-vendor-access
boundary (CLAUDE.md rule 2) for no real benefit, since the harness's whole point is checking the
*node* LLM's behaviour, not simulating a patient; (2) the same deterministic `check_expectations`
used in mock mode is a stricter, more auditable pass/fail gate than an LLM judge's rubric score,
and most of what a real run needs to verify (policy/safety pre-checks, illegal-transition rejection,
outcome routing) is already LLM-independent — only rating/topic/complaint *content* genuinely varies
run to run, which is why scenario authors should prefer `min_rating`/`min_complaint_count` over
exact `rating`/`complaint_count` for any scenario likely to be run in real mode (see
`cases/README.md`).

Usage (inside the api container, where `DATABASE_URL`/provider credentials are configured):
    python -m tests.scenarios.runner --ids S01,S09,S13,S22
    python -m tests.scenarios.runner --sample 5

Writes `reports/scenarios_<timestamp>.md` and `.json`. Exit code is 1 if any sampled scenario
fails or errors (the hard gate), 0 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.gemini.llm import GeminiLLM
from app.adapters.interfaces import LLMAdapter
from app.adapters.registry import AdapterRegistry
from app.db.base import get_superadmin_sessionmaker
from app.services import provider_settings_service
from tests.scenarios.models import load_scenarios
from tests.scenarios.runner_core import ScenarioRunResult, drive_scenario

_REPORTS_DIR = Path(__file__).parent / "reports"


async def _build_real_gemini_registry(session: object) -> AdapterRegistry[LLMAdapter]:
    credentials = await provider_settings_service.get_decrypted_credentials(
        session, ["gemini"]  # type: ignore[arg-type]
    )
    if "gemini" not in credentials:
        raise SystemExit(
            "No saved Gemini API key found (Settings -> Gemini). The real-API sample runner "
            "needs one — it uses the same saved, decrypted key the dashboard uses, never a "
            "hard-coded one."
        )
    api_key, model = credentials["gemini"]
    registry = AdapterRegistry[LLMAdapter]()
    registry.register("gemini", GeminiLLM(api_key=api_key, model=model))
    return registry


async def _run(ids: list[str] | None, sample: int | None) -> list[ScenarioRunResult]:
    all_scenarios = load_scenarios()
    if ids:
        wanted = set(ids)
        scenarios = [s for s in all_scenarios if s.id in wanted]
        missing = wanted - {s.id for s in scenarios}
        if missing:
            raise SystemExit(f"unknown scenario ids: {sorted(missing)}")
    elif sample:
        scenarios = random.sample(all_scenarios, min(sample, len(all_scenarios)))
    else:
        scenarios = all_scenarios

    sessionmaker = get_superadmin_sessionmaker()
    results: list[ScenarioRunResult] = []
    async with sessionmaker() as session:
        registry = await _build_real_gemini_registry(session)
        for scenario in scenarios:
            print(f"--- running {scenario.id}: {scenario.title} ---", file=sys.stderr)
            result = await drive_scenario(session, registry, scenario, provider="gemini")
            await session.commit()
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"    {status} ({result.turns_taken} turns)", file=sys.stderr)
            if result.error:
                print(f"    error: {result.error}", file=sys.stderr)
            for failure in result.failures:
                print(f"    - {failure}", file=sys.stderr)
    return results


def _write_report(results: list[ScenarioRunResult]) -> Path:
    _REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = _REPORTS_DIR / f"scenarios_{stamp}.json"
    md_path = _REPORTS_DIR / f"scenarios_{stamp}.md"

    json_path.write_text(
        json.dumps([asdict(r) for r in results], indent=2, default=str), encoding="utf-8"
    )

    passed = sum(1 for r in results if r.passed)
    lines = [
        f"# Scenario run — {stamp}",
        "",
        f"{passed}/{len(results)} passed.",
        "",
        "| Scenario | Result | Turns | Detail |",
        "|---|---|---|---|",
    ]
    for r in results:
        detail = r.error or "; ".join(r.failures) or "-"
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"| {r.scenario_id} | {status} | {r.turns_taken} | {detail} |")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", help="comma-separated scenario ids, e.g. S01,S09,S13,S22")
    parser.add_argument(
        "--sample", type=int, default=None, help="run a random sample of N scenarios instead"
    )
    args = parser.parse_args()
    ids = args.ids.split(",") if args.ids else None

    results = asyncio.run(_run(ids, args.sample))
    report_path = _write_report(results)
    print(f"\nreport: {report_path}", file=sys.stderr)

    if any((not r.passed) for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
