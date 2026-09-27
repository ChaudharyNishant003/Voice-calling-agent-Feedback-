# PRD v2 — Conversation Graph, Safety Layer & Scenario Harness: Final Report

Status: **all 9 phases complete** (branch `demo-mvp`). This report summarizes what was built, the
decisions made along the way, what was found and fixed by actually running the system (not just
reading it), and what's intentionally out of scope.

## 1. What changed

The Demo MVP's conversation engine was a free-form loop (`domain/conversation_language.py` +
`domain/conversation_topics.py` + `services/demo_conversation_service.py`): one combined LLM call
per turn decided language, topics, response, and when to end. It worked, but had no identity check,
no consent step, no caregiver handling, no safety escalation, no rating, no structured per-call
output, and couldn't be tested systematically.

It's now replaced end to end by a **node-graph engine**
(`backend/app/domain/conversation_graph/`): a fixed set of 16 conversation nodes, the LLM proposing
a next node and content *within* a node, and deterministic code — never the LLM — owning every
transition, safety decision, and escalation (CLAUDE.md rule 3). See the README's "conversation
graph" section for the node diagram, and `docs/11_BUILD_PLAN.md`'s "PRD v2" entries for the detailed
phase-by-phase build log this report summarizes.

## 2. Phase status

| Phase | Scope | Status |
|---|---|---|
| 2 | Engine core (`graph.py`, `state.py`, `policy.py`, `scripts.py`, `normalizer.py`, `guards.py`, `repair.py`) | Done — 351 unit tests |
| 3 | Safety layer (`safety.py`, `severity.py`) | Done — lexicon + LLM-flag OR-merge, S0-S4 routing |
| 4 | LLM integration (9 per-node prompts, `pfa_call_prompts.py`, orchestrator core) | Done — real Gemini smoke-tested across all 9 nodes |
| 5 | Persistence & API (migrations `0016`/`0017`, `pfa_call_service.py`, `pfa_results_service.py`) | Done — 386 tests green |
| 6 | Dashboard (patient/visit form, node chip, escalation banner, results/escalations pages) | Done — live-tested against real Gemini through the actual UI |
| 7 | 40-scenario test harness | Done — 41 tests green (mock mode); real-API sample runner available |
| 8 | Start a call from an already-ingested CSV visit | Done — 396 tests green |
| 9 | README & this report | Done |

## 3. Confirmed decisions (made explicitly, not assumed)

1. **Reused the existing `complaints`/`cases`/`case_events` tables** (migration `0007`) instead of
   the PRD's separate `pfa_complaints`/`pfa_escalations` design — those tables already implement a
   more complete lifecycle (SLA timers, breach flags, audit trail) than the PRD re-specifies.
   Extended them with new nullable columns instead of forking a parallel system.
2. **Gemini stays the practically-tested default.** OpenAI is fully wired into the adapter registry
   and every node prompt is provider-agnostic, but real scenario/smoke testing used Gemini
   throughout, per an explicit decision not to push OpenAI as the practical default before a working
   key is confirmed.
3. **Full replacement**, not a side-by-side engine — `/demo`, `/demo/playground`'s underlying
   engine, everything now runs the node graph. No dead old-engine code path is live (a separate,
   already-flagged cleanup task tracks removing genuinely dead code from
   `demo_conversation_service.py`).
4. **The scenario harness is built in full** (all 40 scenarios, both run modes, the report
   generator), but only a small hand-picked real-API sample is expected to run routinely — the full
   40-scenario real-API gate is a follow-up once API quota/keys are in better shape, per the
   original plan.

## 4. Real bugs found by actually running the system

Reading code and writing unit tests against mocks caught most defects, but five categories of bug
only surfaced by driving real conversations through the real system — first live against the actual
Gemini API through the dashboard (Phase 6), then again by building and running the scenario harness
against the real engine (Phase 7):

1. **Devanagari safety-lexicon boundary bug** (Phase 2/3): `\b` word boundaries rely on Python's
   `\w`, which excludes Devanagari combining vowel signs — so `\b` silently split mid-word for any
   Hindi phrase ending in a matra (e.g. "मरना"), meaning several seeded self-harm/threat phrases
   never matched. Fixed with whitespace-based boundaries.
2. **Length guard truncating FIXED safety scripts** (Phase 4): the emergency-escalation lines and
   consent disclosure legitimately exceed the generic word budget by design; the guard now defaults
   off and is opted into only at the 3 call sites that carry genuine LLM-authored text.
3. **LLM node-name hallucination** (Phase 4, confirmed again independently by the scenario harness
   in Phase 7): the real Gemini API invented node names not in the graph
   (`visit_experience_rating`, `conversation_complete`). `graph.next_node()`'s illegal-transition
   rejection is the reason these calls didn't break — a real, load-bearing safety net, not a
   theoretical one.
4. **`identity_verified`/`respondent_type` never actually set** (Phase 6, live dashboard testing):
   the pre-identity-disclosure guard fired on any later reply mentioning "doctor", silently replacing
   normal agent replies with the consent line for the rest of the call. Fixed in `_apply_transition`.
5. **Topic/complaint duplication** (Phase 6, live dashboard testing): the LLM re-reported a topic or
   complaint still visible in its own recent-history window. Fixed via dedup in `_merge_topics` and
   an `already_logged_complaints` line in the per-turn state summary sent to the LLM.
6. **Silence-timeout callback never set the terminal node** (Phase 7, found while building the
   scenario harness's first real run): `_handle_silence`'s end-call branch set
   `call_outcome=CallOutcome.callback` and `ended=True` but left `state.node` wherever the call
   happened to be — unlike every other path reaching that same outcome (`wants_human`,
   repeat-request give-up, `stt_error` give-up), which all set `node=Node.callback` explicitly.
   Fixed to match; the harness's `S15` scenario now encodes the correct behaviour.

## 5. Known, documented simplifications (not bugs — deliberate scope decisions)

- **`CALLBACK` is a one-shot exit**, not the PRD's two-turn "ask when → confirm slot" — matches
  `graph.py`'s tested terminal-node model, which has no self-loop for it.
- **`ESCALATE_URGENT`'s medical/self-harm follow-up** ("would you like a callback now?") is answered
  by a small deterministic yes/no check rather than a tenth LLM prompt file, since the call proceeds
  to `CLOSE` either way regardless of the answer.
- **Escalations persist every turn they appear**, not only at call-end, since a live medical/
  self-harm handoff must be visible in the queue immediately — not delayed until the patient answers
  the follow-up question.
- **The real-API scenario sample reuses each scenario's own scripted patient text** against the real
  LLM, rather than adding a second LLM-simulated-patient + LLM-judge pair — see
  `tests/scenarios/runner.py`'s module docstring for the full reasoning (avoids putting a
  test-harness-only prompt schema in `app/adapters/`, and the harness's deterministic assertions are
  already a stricter gate than an LLM judge's rubric for anything policy/safety-driven).
- **An explicit "switch to English" request from the patient isn't distinguished from the LLM simply
  detecting English** — `pfa_node_contract.NodeContract` has no separate `requested`-language field,
  so `conversation_language.decide_language`'s `requested` parameter (built for exactly this) is
  never actually reached from `pfa_call_service._apply_language`. In practice this only matters for
  the 3-consecutive-turn streak rule: a *first-ever* customer turn in English still locks
  immediately (no streak needed), which is why the scenario harness's English scenario (`S37`) is a
  pure-English caller rather than a mid-call switch. Noted here rather than fixed, since closing this
  gap means extending the node contract schema and every node prompt — a Phase 4-sized change, not a
  Phase 9 one.

## 6. Test coverage snapshot

- Targeted PRD v2 suite (unit + integration for the conversation graph, persistence, API, migrations,
  scenario harness): 396+ tests, all green.
- `ruff check` / `mypy --strict` / `lint-imports` clean on every changed file.
- Dashboard: `eslint` / `tsc --strict` clean; manually driven through real multi-turn calls in
  Chrome against the real Gemini API (Phase 6), including the escalation banner, results list/detail,
  and escalations queue.

## 7. Out of scope (unchanged from before this PRD)

Real telephony (Plivo), the LiveKit agent runtime, Deepgram STT, Cartesia TTS, and the production
dial/retry/webhook pipeline (Sprints 2-4 in `docs/11_BUILD_PLAN.md`) are untouched by this work — the
Demo MVP is a browser-based stand-in for the conversation engine specifically, per CLAUDE.md's phase
gate (rule 1) and the existing Demo MVP scope.
