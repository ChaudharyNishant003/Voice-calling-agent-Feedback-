"""Scenario schema + YAML loader (PRD v2 Phase 7).

A scenario is a fixed, ordered list of patient turns driven through the real
`pfa_call_service` orchestrator (`start_call`/`submit_turn`/`end_call`) — the harness never
re-implements engine behaviour, it only supplies inputs and checks outputs. Each turn carries the
actual `patient_text` that reaches `process_turn`, so `policy.py`'s opt-out/wants-human/
repeat-request checks and `safety.py`'s lexicon scan run for real, not simulated, plus an optional
`contract` — the canned `NodeContract` fields to hand back the one time (if any) `process_turn`
actually calls the node LLM for that turn.

Whether a turn calls the LLM at all depends entirely on the engine's own pre-LLM short-circuits
(safety keyword hit, opt-out/wants-human policy match, `silence`/`stt_error` event kind, or the
deterministic `escalate_urgent` follow-up yes/no) — see `pfa_call_service.process_turn`. A scenario
author must get this right for `--mock-llm` mode's contract queue to line up 1:1 with actual LLM
invocations; `mock_llm.ScenarioLLM` raises loudly rather than guessing if the queue runs dry.

Scenario content under `cases/*.yaml` is this session's own design (deliberately built to cover
every node-graph edge, all 8 safety categories, and every repair/policy path) rather than verbatim
text from the source PRD document, which was supplied out-of-repo and isn't available here — see
docs/11_BUILD_PLAN.md's Phase 7 entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

EventKind = Literal["utterance", "silence", "stt_error"]


@dataclass(frozen=True)
class Turn:
    patient_text: str
    event_kind: EventKind = "utterance"
    contract: dict[str, object] | None = None


@dataclass(frozen=True)
class Visit:
    visit_type: str = "OPD"
    patient_first_name: str = "Ramesh"
    patient_phone: str | None = None
    patient_age: int | None = None
    department: str | None = None
    doctor_name: str | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    tags: tuple[str, ...]
    visit: Visit
    persona: str
    turns: tuple[Turn, ...]
    expect: dict[str, object]
    rubric: str | None = None
    path: Path | None = field(default=None, compare=False)


def _load_one(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    visit_raw = raw.get("visit", {})
    turns = tuple(
        Turn(
            patient_text=t["patient_text"],
            event_kind=t.get("event_kind", "utterance"),
            contract=t.get("contract"),
        )
        for t in raw.get("turns", [])
    )
    return Scenario(
        id=raw["id"],
        title=raw["title"],
        tags=tuple(raw.get("tags", [])),
        visit=Visit(**visit_raw),
        persona=raw.get("persona", ""),
        turns=turns,
        expect=raw.get("expect", {}),
        rubric=raw.get("rubric"),
        path=path,
    )


def load_scenarios(directory: Path | None = None, *, ids: set[str] | None = None) -> list[Scenario]:
    directory = directory or (Path(__file__).parent / "cases")
    scenarios = [_load_one(p) for p in sorted(directory.glob("*.yaml"))]
    if ids is not None:
        scenarios = [s for s in scenarios if s.id in ids]
    return scenarios
