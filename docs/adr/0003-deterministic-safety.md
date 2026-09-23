# 0003 — Deterministic safety, consent, and escalation

Status: Accepted

## Context
PFA calls patients about their own healthcare visit and must never let a probabilistic model be
the sole gate on consent, opt-out, emergency/safety detection, escalation creation, retention, or
identity validation (CLAUDE.md §4 rule 3). LLMs are useful for language understanding but are not
auditable or reliably conservative enough to be trusted alone on paths where the cost of a false
negative is a missed medical emergency or a compliance violation.

## Decision
Consent, opt-out, safety/emergency detection, and escalation creation are deterministic code paths
in `app/domain` (`consent.py`, `safety.py`, `escalation.py`, `case_lifecycle.py`) driven by
lexicons and rules, tested to 100% branch coverage (doc 08 §1). The LLM may *suggest* — e.g. raise
a suggested urgency tier — but deterministic code *decides*, and urgency resolution always takes
`max(rule_tier, llm_tier)` (doc 01 §3 `urgency.py`), never the reverse. When in doubt, the system
escalates higher, never downgrades (CLAUDE.md §4 rule 6). Consent/greeting audio is pre-rendered,
never LLM-generated (CLAUDE.md §4 rule 4).

## Consequences
- The safety golden set (doc 08 §5) gates CI at 100% recall on the emergency subset for the
  rule-only pipeline — a regression here fails the build, not just a review comment.
- This trades some flexibility (a novel phrasing the lexicon doesn't cover may under-trigger) for
  auditability: every safety/consent/escalation decision can be replayed and explained without
  needing to re-run an LLM or trust its non-determinism.
- Sprint 0 ships the adapter seam this relies on (LLM never bypasses the deterministic layer,
  enforced by the same import-linter boundary as ADR 0002) even though the lexicons themselves
  land in Sprint 3-4.
