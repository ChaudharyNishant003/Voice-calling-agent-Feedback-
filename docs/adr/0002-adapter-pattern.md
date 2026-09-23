# 0002 — Adapter-only vendor access

Status: Accepted

## Context
PFA depends on four swappable vendors (telephony, STT, LLM, TTS) plus email/storage, each chosen
under real uncertainty (doc 12 open questions #5, #7, #16). Business logic that calls a vendor SDK
directly becomes expensive to test (needs live credentials or elaborate mocking) and expensive to
change (a vendor swap touches every call site).

## Decision
`backend/app/domain` and `backend/app/services` never import a vendor SDK (CLAUDE.md §4 rule 2).
All vendor access goes through Protocols in `app/adapters/interfaces.py`
(`TelephonyAdapter`, `STTAdapter`, `LLMAdapter`, `TTSAdapter`, `NotificationAdapter`,
`ObjectStorageAdapter`), each vendor gets its own package under `app/adapters/<vendor>/`, and
`app/adapters/fakes/` provides deterministic fakes that satisfy the same Protocols for tests and
local dev. `app/adapters/registry.py` resolves the concrete adapter by `(capability, language,
account)` from config, wrapped in a circuit breaker (doc 06 §3) so a failing vendor can't cascade
into placing calls it can't finish.

An import-linter contract (`backend/pyproject.toml`) enforces the boundary mechanically — a
domain-or-service import of a vendor package fails CI, not just code review.

## Consequences
- Every test in Sprint 0-onward runs against fakes; no test suite needs real Plivo/Deepgram/
  Gemini/Cartesia credentials to pass (docs/10_DEPLOYMENT_AND_OPS.md §1 — `ci` env is Fakes-only).
- Adding a regional STT provider (Open Question #5) or replacing a vendor after a bad pilot result
  is a new adapter package + a registry entry — zero changes to domain or services.
- The cost is one extra layer of indirection (Protocol + adapter + fake) per vendor capability,
  accepted deliberately given how unsettled the vendor choices still are.
