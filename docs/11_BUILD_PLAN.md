# 11 — Build Plan (Phase 1 / MVP)

How to use: work top to bottom. Each task has a **Done when** check. Tick the box in the PR that
completes it. Do not start a sprint until the previous sprint's exit check passes. Sprints are ~1 week
of focused work each; order matters more than duration.

Parallel business track (not code, but blocking production): OPEN QUESTIONS #1, #2, #3, #5, #8.

---

## Sprint 0 — Foundations
- [x] **S0.1 Monorepo scaffold** (backend, dashboard, eval, infra) per doc 01 §3.
  Done when: `make up` starts all services; `/health/ready` green; dashboard login page renders.
- [x] **S0.2 Tooling**: ruff, mypy strict, eslint, tsc strict, import-linter contracts (domain/services
  cannot import adapters' vendor modules), pre-commit + gitleaks.
  Done when: `make lint` passes and a deliberate violation fails.
- [x] **S0.3 Core**: settings, structlog + redaction processor, error hierarchy + FastAPI handler,
  UUIDv7 prefixed IDs, injectable clock, phone normalisation/hash.
  Done when: unit tests for redaction (no phone/text leaks), error envelope, E.164 cases.
- [x] **S0.4 Adapter interfaces + fakes + registry + circuit breaker.**
  Done when: fakes satisfy Protocols (mypy), failure injection works.
- [x] **S0.5 Observability base**: Prometheus endpoint, OTel tracing, Sentry scrubbed, `call_events` writer.
  Note: `call_events` writer is an in-memory seam (`app/services/metrics_service.py`) until the
  table lands in S1.1 — see that module's docstring.
- [x] **S0.6 CI pipeline** (doc 08 §11) + ADRs 0001–0004.
Exit: CI green on scaffold; ADRs merged. ✅ Verified locally: ruff/mypy --strict/import-linter/
bandit clean, 47 unit tests pass, full docker-compose stack boots with all services healthy and
the dashboard login stub renders. GitHub Actions CI itself has not run yet (no remote/PR).

## Sprint 1 — Data, auth, ingestion, eligibility
- [x] **S1.1 Migrations 0001–0011** (doc 02 §6) incl. RLS + grants; up/down/up in CI.
  Verified: up/down/up run clean against a real Postgres; RLS confirmed on tenant tables
  (`relrowsecurity=t`); `pfa_app`/`pfa_superadmin` roles + grants match doc 02 §3 (see that doc's
  §3 note — both keep SELECT on `audit_log`, only UPDATE is revoked; an earlier "INSERT only for
  pfa_app" reading turned out to be self-defeating, caught by an actual test failure).
  Local note: testcontainers-in-a-container hits a Docker-Desktop-for-Windows networking quirk —
  fixed by setting `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal` (and
  `TESTCONTAINERS_RYUK_DISABLED=true`, since the reaper sidecar hits the same issue) when running
  `pytest tests/integration` from inside a docker-outside-of-docker validation container on this
  machine. Not needed in CI (native Linux runner, doc 10 §4).
- [x] **S1.2 Encryption helpers** (envelope AES-GCM, KMS local provider, HMAC phone hash).
  Done when: DB scan test finds no plaintext phones/transcripts. Verified — see
  `tests/integration/test_encryption_no_plaintext.py`.
- [ ] **S1.3 Auth**: login, refresh rotation, logout, lockout, MFA TOTP, password reset, CSRF, RBAC
  permission map + route-permission completeness test.
  **Partial — increment 3a done, 3b open.** Built: password hashing (argon2id) + strength policy,
  JWT access/refresh sessions with rotation + reuse detection, lockout (5 attempts / 15 min), RBAC
  permission map + route-completeness test, CSRF (double-submit cookie), `refresh_tokens` table
  (migration 0012, Open Question #23 — not in doc 02's DDL). Verified against real Postgres
  (`tests/integration/test_auth_service.py`, `test_auth_api.py`) and manually through the running
  `docker compose` stack (`login` -> `/me` -> `refresh` -> `logout`). That manual pass caught a real
  bug unit/integration tests missed: the refresh cookie was named `__Host-pfa_refresh` but scoped to
  `Path=/api/v1/auth` — the `__Host-` prefix *requires* `Path=/` exactly, so real clients (curl,
  every major browser) silently refuse to store it at all, which would have made `/auth/refresh`
  permanently broken in any real browser despite every automated test passing (httpx's cookie jar
  doesn't enforce the `__Host-` prefix rule). Fixed by moving both `__Host-` cookies to `Path=/`; a
  regression test now asserts `Path=/`+`Secure` on any `__Host-`-prefixed Set-Cookie header
  (`test_login_sets_all_three_cookies`). That same manual pass also found `infra/docker/
  api.Dockerfile` never copied `alembic.ini` into the image, so `make migrate` could never actually
  run against the compose Postgres — fixed by adding the `COPY`. Still open for 3b: MFA TOTP +
  recovery codes (doc 07 §2 requires MFA for admin/super_admin — not enforced yet),
  `/auth/password/forgot`/`reset`.
- [x] **S1.4 Audit service** with hash chain + nightly verify task.
  Verified: `tests/unit/test_audit_chain.py` (hash/verify logic, incl. a corrected cross-row
  linkage check — an earlier version only checked each row's self-consistency, which misses real
  tampering; see `domain/audit_chain.py`'s docstring), `tests/integration/test_audit_service.py`
  (sequential + concurrent `record()` calls produce one valid chain — the `pg_advisory_xact_lock`
  actually serializes writers). Nightly task registered and confirmed in a live `celery` worker's
  `[tasks]` list (`app.workers.tasks.audit.verify_audit_chain`) — this caught a real bug where
  `autodiscover_tasks(["app.workers.tasks"])` silently registered nothing (see `celery_app.py`).
- [ ] **S1.5 Accounts/locations/departments/users APIs** + activation guard (PFA-ACC-003).
- [ ] **S1.6 Ingestion**: upload endpoint, CSV parser in worker, all row validations/codes, batch
  thresholds, duplicate SHA, template download, SFTP poller (per-account chroot folder).
  Done when: 50k-row synthetic file processed < 2 min; every PFA-ING code covered by a test.
  **Partial — core pipeline done, SFTP open.** Built: `POST /ingestion/uploads` (multipart,
  `require(Permission.upload_lists)`), batch list/get/errors endpoints, `GET /ingestion/
  template.csv`; `services/ingestion_service.py` (sync pre-checks — extension, size, encoding,
  header columns, duplicate SHA — all before the Celery job is even enqueued, so bad files fail
  fast instead of going through "received" then "failed"); `domain/ingestion_csv.py` (pure
  per-row validators, every `PFA-ING-01x` code); `workers/tasks/ingestion.py` (parses, creates
  `Patient`/`Visit`, auto-creates unmapped departments, applies the configurable `PFA-ING-003`
  threshold via a savepoint so a rejected batch leaves no `Patient`/`Visit` rows behind while still
  keeping the row errors that explain why, then runs the already-built `eligibility_service` on
  every created visit — this is the actual Sprint-1-exit-criterion line). Verified against real
  Postgres (`tests/integration/test_ingestion_service.py`, `test_ingestion_api.py`) and a 50k-row
  wall-clock check (`test_ingestion_perf.py`, opt-in via `-m slow`, doc 08 §6). Still open: SFTP
  poller (`GET /ingestion/sftp`, `POST /ingestion/sftp/keys`, beat schedule) — not required by
  this item's "Done when", deferred as its own chunk of work.

  Gaps found and filled while building this (each logged in `docs/12_OPEN_QUESTIONS.md`, not
  guessed silently): doc 04 §4's two "configurable"/"account setting" ingestion knobs
  (`PFA-ING-003` threshold, visit-date format) had no columns anywhere — added
  `accounts.ingest_error_threshold_pct`/`ingest_date_format` (migration 0013, Open Question #24).
  The worker needs the raw uploaded bytes, but the S3 storage adapter is a deliberate stub deferred
  to Sprint 3 — added `ingestion_batches.content bytea` as a Sprint-1 stopgap with no retention/
  purge job yet (migration 0014, Open Question #25). No error code existed for "batch not found"
  (including cross-tenant, per doc 04 §1) — added `PFA-ING-007` to doc 06. Also fixed a
  pre-existing gap this increment was the first to actually exercise: `LOCAL_KEK_BASE64` in
  `.env`/`.env.example` was a placeholder that isn't valid base64 (`load_kek_from_base64` would
  have raised on first real use — nothing before ingestion ever read it outside a test's own ad hoc
  KEK).

  Manual verification against the real `docker compose` stack (seeded account, real login, real
  multipart upload, real Celery worker) caught a second real bug the automated suite couldn't have:
  a worker process crashed processing its *second* task, not its first. `db.base`'s engines are
  `@lru_cache`d at process scope, but each Celery task ran its body via a fresh `asyncio.run()`,
  which tears down its event loop when the task finishes — and an asyncpg connection pool is bound
  to the loop it was created on. Task 1 built the engine against loop A; when loop A closed, task 2
  got a new loop B but `get_engine()` still handed back the loop-A-bound engine, and asyncpg raised
  `Future ... attached to a different loop`. This also affected the pre-existing `S1.4` audit task,
  not just this one — a real `celery worker` processing more than one `verify_audit_chain`/
  `process_ingestion_batch` run in its lifetime would eventually have crashed. Fixed with a shared
  `workers/task_utils.run_worker_task()` that disposes and clears the cached engines *inside the
  same event loop* the task ran in (disposing from a *later* `asyncio.run()` call fails too —
  `Event loop is closed` — since asyncpg can't gracefully close a connection from a different loop
  than the one it was opened on; also confirmed by hand). Verified by uploading three sequential
  batches (including one that exceeds the threshold) through the real running stack and confirming
  the same worker fork processes all three without crashing.
- [x] **S1.7 Eligibility engine** (pure) + service; review *resolution* (`resolve_review`) built and
  tested, but the `POST /visits/{id}/review` HTTP route itself is deferred to S1.5 (needs auth).
  Done when: rule tests + hypothesis property tests pass; suppression reasons stored. Verified —
  `tests/unit/test_eligibility.py` (all 11 rules, precedence, idempotence, hypothesis properties),
  `tests/integration/test_eligibility_service.py` (real-Postgres rule scenarios incl. shared-number
  review → `resolve_review` → matching audit row, all in doc 07 §6's required same-transaction).
- [ ] **S1.8 Suppression API** (add/check/remove-manual) + opt-out immutability.
Exit: upload a synthetic CSV → visits with correct eligibility; audit rows exist.

## Sprint 2 — Orchestration & telephony
- [ ] **S2.1 Contact window + retry policy** (pure) with exhaustive boundary tests.
- [ ] **S2.2 Dial service + beat dial tick** (30 s): window, daily cap, concurrency semaphore, pre-dial
  recheck in a locked transaction, attempt creation.
- [ ] **S2.3 Plivo adapter**: place_call, hangup, transfer, signature verification, status parsing; AMD.
- [ ] **S2.4 Webhooks**: answer (bridge to LiveKit SIP), status, machine; idempotent; out-of-order safe.
- [ ] **S2.5 Concurrency reaper** + leak metric.
- [ ] **S2.6 Non-prod allowlist guard** + startup validation.
Exit: staging places a real call to an allowlisted phone that is bridged into a LiveKit room; zero
dials outside window in a frozen-clock integration test.

## Sprint 3 — Agent runtime: consent & deterministic survey
- [ ] **S3.1 LiveKit agent entrypoint + CallSession** with per-turn persistence of `CallState`.
- [ ] **S3.2 Deepgram STT adapter** (8 kHz, streaming, language hints, keyword boosts for hospital/
  department names).
- [ ] **S3.3 Cartesia TTS adapter** + audio pre-render job + cache (`audio/manifest.yaml`),
  pronunciation dictionary support.
- [ ] **S3.4 Consent state machine** (deterministic lexicons EN/HI), short-form rule on early barge-in,
  commit-before-continue.
- [ ] **S3.5 Call state machine** (doc 03 §3) with global interrupts, identity step, deterministic answer
  interpretation, answered_fields, reprompts, silence, max duration.
- [ ] **S3.6 Safety detector** (lexicon YAML, transliteration) + emergency path (sync P1 case creation
  + fallback table + alert) + clinical boundary.
- [ ] **S3.7 Opt-out, stop, recording withdrawal** handlers (stop egress).
- [ ] **S3.8 Barge-in & endpointing tuning** hooks (config per language).
- [ ] **S3.9 Text-mode simulator** (`make sim`) + scenarios S01–S07, S10, S12–S20, S24–S29.
Exit: all listed scenarios pass with fake adapters; a real staging call completes consent + 3 questions
in English and Hindi.

## Sprint 4 — LLM: interpretation, probing, extraction
- [ ] **S4.1 Gemini adapter** with JSON-schema-constrained output, timeouts, token accounting.
- [ ] **S4.2 Prompt registry** (versioned YAML + schemas), prompt version recorded per call.
- [ ] **S4.3 interpret_answer** integration (only when deterministic fails) + confidence handling.
- [ ] **S4.4 probe_generate** + deterministic guard + fallback probe + caps.
- [ ] **S4.5 Post-call extraction worker**: extract_call, verbatim substring validation + offsets from
  turns, taxonomy validation, urgency max(rule, llm), malformed retry, human-review flag.
- [ ] **S4.6 Complaint creation** + multi-department complaints.
- [ ] **S4.7 Scenarios** S08, S09, S11, S21–S23, S30–S32; safety golden set v1 (≥ 300) + CI gate.
Exit: golden-set gates met; deterministic turn ratio ≥ 70% in simulated runs.

## Sprint 5 — Escalation & cases
- [ ] **S5.1 Escalation mapping + SLA calc** (pure) + tests.
- [ ] **S5.2 Case service** with lifecycle guards, optimistic locking, merge rules, second-user
  confirmation for P1 invalidation, audit + case_events.
- [ ] **S5.3 Case APIs** (doc 04 §7).
- [ ] **S5.4 SLA ticker** (every minute): breach flags, re-alerts (30 min P1), breach emails.
- [ ] **S5.5 Notification service**: P1 immediate, P2 batched, daily digest, weekly summary, breach;
  idempotency keys; templates (HTML + text) with no PII.
- [ ] **S5.6 Human review queue** for safety/low-confidence calls (API).
Exit: simulated negative call → case → full lifecycle to closed with correct SLA and emails in mailpit.

## Sprint 6 — Dashboard
- [ ] **S6.1 App shell**: auth pages, layout, nav, account/location switcher, date range, ⌘K search,
  i18n messages file from doc 06 catalogue, error/empty/loading patterns.
- [ ] **S6.2 Queue + Case detail** (keyboard shortcuts, evidence card with clip playback, actions).
- [ ] **S6.3 Closure, Departments, Doctors (n ≥ 5 rule), Locations.**
- [ ] **S6.4 Operations + Data quality** (incl. shared-number review, department mapping).
- [ ] **S6.5 Calls list + Call detail** (transcript, audio, extracted fields, events/replay, review).
- [ ] **S6.6 Settings** (account, SLA, retention, departments, users, survey editor + audio preview,
  ingestion, suppression, deletion, audit log).
- [ ] **S6.7 Playwright flows + axe accessibility checks.**
- [ ] **S6.8 Demo seed** (`make seed-demo`).
Exit: a quality user can triage, acknowledge, assign, resolve, and close a case in < 2 minutes in a
usability walkthrough; all 8 views populated from seed data.

## Sprint 7 — Retention, deletion, compliance, cost
- [ ] **S7.1 Retention jobs** (audio hourly, transcripts/verbatims/calls daily) + S3 lifecycle backstop
  + 410 handling.
- [ ] **S7.2 Deletion workflow** (request, second-person approval, idempotent job, report).
- [ ] **S7.3 Patient data export** (JSON) for fiduciary access requests.
- [ ] **S7.4 Compliance checks service** (nightly queries from doc 08 §9) + alerts.
- [ ] **S7.5 Cost telemetry**: rates table, per-call breakdown, cost dashboard, anomaly alert.
- [ ] **S7.6 Subprocessor page** in Settings → Compliance.
Exit: frozen-clock tests prove purge/deletion; every completed simulated call has a cost breakdown.

## Sprint 8 — Hardening & pilot readiness
- [ ] **S8.1 Latency harness** on staging PSTN (EN, HI, Hinglish; noise conditions) + tuning.
- [ ] **S8.2 STT WER report** per language; regional-language candidate evaluation (when chosen).
- [ ] **S8.3 Load test** at 2× computed peak.
- [ ] **S8.4 Security scans clean** + ZAP baseline + tenant-isolation suite; external pentest (business).
- [ ] **S8.5 Runbooks** written and dry-run (pause, safety failure, breach tabletop).
- [ ] **S8.6 Native-speaker review** of all Hindi (and regional) scripts; re-render audio.
- [ ] **S8.7 Pilot onboarding checklist** (doc 10 §7) executed on staging with the pilot's config.
- [ ] **S8.8 Acceptance dry run**: run the doc 08 §9 checklist on staging traffic; fix gaps.
Exit: ready for pilot go-live; production acceptance measured during the 6–8 week pilot.

---

## Phase 2 backlog (do NOT start until Phase 1 gate passes)
REST/webhook ingestion · +2 regional languages benchmarked & routed · multi-location RBAC · SSO + audit
export · callback preferred-time learning · taxonomy suggestion & theme clustering · longitudinal
analytics · India-region/BYOC doc for an enterprise prospect · WhatsApp/SMS fallback · outbound webhooks
(schema already in doc 04 §11).

## Phase 3 backlog (after two paid renewals)
FHIR/ABDM · no-code policy console · in-house eval datasets · outcome analytics · anonymised
benchmarks · vertical variant · predictive risk scoring.
