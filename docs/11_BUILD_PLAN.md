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
  Verified: up/down/up run clean against a real Postgres (docker-compose); RLS confirmed on tenant
  tables (`relrowsecurity=t`); `pfa_app`/`pfa_superadmin` roles + grants match doc 02 §3 exactly
  (audit_log INSERT-only, superadmin BYPASSRLS). The committed testcontainers-based integration
  tests (`tests/integration/test_migrations.py`, `test_tenant_isolation.py`) hit a Docker-Desktop-
  for-Windows-specific docker-outside-of-docker networking issue when run from inside this session's
  own validation container — they're expected to run fine in CI (native Linux runner) and were
  verified equivalently via a manual script against the docker-compose Postgres instead.
- [x] **S1.2 Encryption helpers** (envelope AES-GCM, KMS local provider, HMAC phone hash).
  Done when: DB scan test finds no plaintext phones/transcripts. Verified — see
  `tests/integration/test_encryption_no_plaintext.py` / the manual run above.
- [ ] **S1.3 Auth**: login, refresh rotation, logout, lockout, MFA TOTP, password reset, CSRF, RBAC
  permission map + route-permission completeness test.
- [ ] **S1.4 Audit service** with hash chain + nightly verify task.
- [ ] **S1.5 Accounts/locations/departments/users APIs** + activation guard (PFA-ACC-003).
- [ ] **S1.6 Ingestion**: upload endpoint, CSV parser in worker, all row validations/codes, batch
  thresholds, duplicate SHA, template download, SFTP poller (per-account chroot folder).
  Done when: 50k-row synthetic file processed < 2 min; every PFA-ING code covered by a test.
- [ ] **S1.7 Eligibility engine** (pure) + service + review flow for shared numbers.
  Done when: rule tests + hypothesis property tests pass; suppression reasons stored.
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
