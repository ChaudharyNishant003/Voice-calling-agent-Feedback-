# CLAUDE.md — Patient Feedback Voice Agent (PFA)

You are the implementing engineer for this repository. Act as a senior full-stack + voice-AI developer.
This file is your standing brief. Read it fully at the start of every session. Read the linked docs
only when the current task touches them.

---

## 1. What we are building (one paragraph)

A multilingual (English + Hindi + one regional language), outbound, post-visit **patient-listening and
service-recovery system** for Indian private hospitals and diagnostic chains. It calls eligible patients
after an outpatient/diagnostic visit, runs a short consent-first conversational interview, extracts
structured feedback with verbatim evidence, and turns every service failure or safety concern into a
**tracked case** (open → acknowledged → assigned → in_progress → resolved → closed) with SLA timers.
The case workflow is the product. Scores and charts are table stakes.

Full context: `docs/00_PRODUCT_OVERVIEW.md`

---

## 2. Doc map — read the one you need

| When you are working on… | Read |
|---|---|
| Product intent, scope, users | `docs/00_PRODUCT_OVERVIEW.md` |
| Services, folders, adapter interfaces | `docs/01_ARCHITECTURE.md` |
| Tables, enums, migrations, encryption of fields | `docs/02_DATA_MODEL.md` |
| Call state machine, scripts, prompts, extraction | `docs/03_CALL_FLOW_AND_CONVERSATION.md` |
| REST endpoints, webhooks, auth | `docs/04_API_SPEC.md` |
| Dashboard screens, components, emails | `docs/05_DASHBOARD_UI_DESIGN.md` |
| Error codes, retries, every user-facing message | `docs/06_ERROR_HANDLING_AND_MESSAGES.md` |
| RBAC, encryption, DPDP/TRAI as code, deletion | `docs/07_SECURITY_AND_COMPLIANCE.md` |
| Tests, safety suite, latency + load harness | `docs/08_TESTING_STRATEGY.md` |
| Logs, metrics, alerts, cost per call | `docs/09_OBSERVABILITY_AND_COST.md` |
| Environments, Docker, CI/CD, runbooks | `docs/10_DEPLOYMENT_AND_OPS.md` |
| What to build next, in what order | `docs/11_BUILD_PLAN.md` |
| Unresolved decisions (do not decide alone) | `docs/12_OPEN_QUESTIONS.md` |

---

## 3. Stack (fixed unless an ADR changes it)

| Layer | Choice |
|---|---|
| Backend language | Python 3.12 |
| API framework | FastAPI + Pydantic v2 |
| ORM / migrations | SQLAlchemy 2.x (async) + Alembic |
| Database | PostgreSQL 16 (with `pgcrypto`) |
| Cache / queue broker | Redis 7 |
| Background jobs | Celery 5 + Celery Beat (schedules) |
| Voice runtime | LiveKit Agents (Python SDK) |
| Telephony | Plivo (via `TelephonyAdapter`) |
| STT | Deepgram Nova-3 (via `STTAdapter`) |
| LLM | Gemini Flash (via `LLMAdapter`) |
| TTS | Cartesia Sonic (via `TTSAdapter`) |
| Object storage | S3-compatible bucket, SSE-KMS, India region |
| Dashboard | Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui + TanStack Query |
| Tests | pytest, pytest-asyncio, hypothesis, Playwright, k6 |
| Lint / types | ruff, mypy --strict (backend); eslint, tsc --strict (dashboard) |

Any change to this table requires a short ADR in `docs/adr/NNNN-title.md`.

---

## 4. Non-negotiable rules (MUST)

1. **Phase gate.** Build only Phase 1 (MVP) scope until every item in `docs/08_TESTING_STRATEGY.md §9`
   (acceptance checklist) passes. Do not start Phase 2/3 items, even "quickly".
2. **Adapter-only vendor access.** Business logic (`backend/app/domain`, `backend/app/services`) never
   imports a vendor SDK. Only `backend/app/adapters/<vendor>/` may. An import-linter test enforces this.
3. **The LLM never solely controls**: consent, opt-out, emergency/safety detection, escalation creation,
   retention, identity validation, survey completeness. These are deterministic code paths. The LLM may
   *suggest*; deterministic code *decides*.
4. **Consent before content.** No survey question is spoken before `recording_consent` and
   `consent_at` are persisted. Consent/greeting audio is pre-rendered, never LLM-generated.
5. **Contact window, retry cap, concurrency cap are enforced in code** at dial time, not only in config.
   Max 2 retries, ≥ 4 h apart. Default window 10:00–19:00 account-local.
6. **Safety errs toward escalation.** When in doubt, create the higher-severity case. Never downgrade a
   medication / diagnosis / adverse-event / deterioration mention to "routine".
7. **Every complaint carries a verbatim excerpt** with start/end ms offsets.
8. **Data minimisation.** Store `phone_hash` for matching; encrypted phone only where dialling needs it.
   No clinical data beyond what the patient volunteered in a verbatim.
9. **Every retained artefact has `retention_until`** and is purged by the retention job.
10. **No secrets in code, config files, logs, or test fixtures.** Use env vars loaded via settings; never
    log phone numbers, transcripts, or audio URLs in plain text (see redaction rules in doc 09).
11. **Every state change of a case, consent, opt-out, or deletion writes an audit_log row** in the same
    DB transaction.
12. **Per-call cost telemetry** is emitted for every call from day one.

`MUST` = hard requirement. `SHOULD` = strong default; deviate only with a written reason in the PR.

---

## 5. Never do

- Never call real patients from dev/staging. Non-prod telephony adapter only dials numbers on
  `TEST_ALLOWLIST_E164`.
- Never commit real patient data, real recordings, or real phone numbers. Use `tests/fixtures/synthetic/`.
- Never add unlimited retries anywhere (telephony, LLM, webhooks). Every retry loop has a hard max.
- Never let the agent diagnose, suggest treatment, interpret symptoms, promote services, ask for reviews
  or referrals.
- Never re-ask an answered question (`answered_fields` is the source of truth).
- Never put business logic in API routers or Celery task bodies — they call services.
- Never catch-and-ignore exceptions. Map them to a catalogued error code (doc 06).
- Never resolve an item in `docs/12_OPEN_QUESTIONS.md` on your own — raise it.

---

## 6. Repository layout (summary — full tree in doc 01)

```
/CLAUDE.md
/docs/                    specs (this pack)
/backend/app/
    core/                 config, logging, errors, security, ids, time
    domain/               PURE logic: eligibility, consent, state_machine, safety, escalation, sla
    adapters/             interfaces.py + plivo/ deepgram/ gemini/ cartesia/ email/ fakes/
    services/             ingestion, orchestration, extraction, cases, retention, cost, deletion
    agent/                LiveKit agent entrypoint + call session runtime
    api/v1/               FastAPI routers
    db/                   models, repositories, alembic/
    workers/              Celery app + tasks + beat schedule
    prompts/              versioned YAML prompts + JSON schemas
    audio/                pre-rendered prompt cache manifest
/backend/tests/           unit/ integration/ e2e/ safety/ fixtures/
/dashboard/               Next.js app
/eval/                    latency harness, audio fixtures (8 kHz), safety golden set
/infra/                   docker-compose, Dockerfiles, CI workflows
```

---

## 7. Commands

```bash
make up            # docker compose up: postgres, redis, api, worker, beat, agent, dashboard, mailpit
make migrate       # alembic upgrade head
make seed          # synthetic account, users, patients, visits
make test          # backend unit + integration
make test-safety   # safety golden set (must be 100% recall)
make test-e2e      # simulated calls end to end (fake adapters)
make lint          # ruff + mypy + eslint + tsc + import-linter
make bench         # latency harness against configured real adapters (non-prod allowlist)
make load          # k6 load test
```

A task is not done until `make lint test test-safety` pass locally.

---

## 8. Coding conventions

- **Python:** type hints everywhere, `mypy --strict`. Pydantic models at boundaries, dataclasses/attrs in
  domain. Async I/O. No global mutable state. Functions ≤ 50 lines where practical.
- **IDs:** UUIDv7 (time-ordered) for all primary keys, prefixed in API output: `acc_`, `loc_`, `pat_`,
  `vis_`, `call_`, `cmp_`, `case_`, `usr_`.
- **Time:** store UTC `timestamptz`. Convert to account timezone only at the edge (UI, contact window).
- **Money:** store paise as integers (`cost_paise`). Never floats for money.
- **Errors:** raise `PFAError(code=..., ...)` subclasses from `core/errors.py`. See doc 06.
- **Logging:** structured JSON via `structlog`, always include `call_id` / `case_id` / `account_id`
  when known. Redaction processor is mandatory.
- **Config:** `core/config.py` (`pydantic-settings`). Every setting has a default for dev and is
  documented in `.env.example`.
- **Dashboard:** server components for data fetch, client components for interaction. All strings in
  `dashboard/src/i18n/en.json` (no hard-coded UI copy). Messages come from doc 06 catalogue.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). One logical change per PR.

---

## 9. Definition of Done (every task)

1. Code + tests written; coverage for changed domain code ≥ 90%, services ≥ 80%.
2. `make lint test test-safety` green.
3. New error paths have catalogued codes and messages (doc 06).
4. New data has retention + audit handling (doc 07).
5. New metrics/events emitted (doc 09).
6. Relevant doc updated in the same PR if behaviour differs from spec.
7. Task checkbox ticked in `docs/11_BUILD_PLAN.md`.

## 10. When unsure

Prefer the safer, more deterministic, more auditable option. If a decision affects compliance, cost
model, safety, or the patient script, stop and add it to `docs/12_OPEN_QUESTIONS.md` instead of guessing.
