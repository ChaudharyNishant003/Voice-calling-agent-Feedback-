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
  **Partial — increment 3a done, 3b PAUSED for the Demo MVP pivot** (see that section below —
  resume 3b after the demo). Built: password hashing (argon2id) + strength policy,
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
  **PAUSED for the Demo MVP pivot** — see that section below.
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
  **PAUSED for the Demo MVP pivot** — see that section below.
Exit: upload a synthetic CSV → visits with correct eligibility; audit rows exist.

## Demo MVP (branch `demo-mvp`) — browser voice feedback demo

Sprint order above paused (S1.3b, S1.5, S1.8) to deliver a fast, browser-based client demo — a
standalone spoken Hinglish/Hindi/English feedback conversation the product owner can run
themselves in Chrome, no login, no real telephony. Built alongside the existing Sprint-1 code
without modifying any of it; resume the paused items once the demo has served its purpose.

**Backend.** Migration `0015_demo_mvp` adds two tables with no RLS (platform/demo-operator config,
not tenant data — same treatment as the pre-existing `cost_rates`): `provider_credentials`
(per-provider API key, encrypted directly with the local KEK — no per-account DEK, since there's
no tenant to scope it to) and `demo_settings` (hospital/agent name, voice gender, singleton row).
`domain/conversation_language.py` and `domain/conversation_topics.py` are pure, I/O-free rules —
the deterministic language-lock (Hindi/Hinglish as one family, a real switch only after 3
consecutive off-family turns, explicit request overrides immediately) and the end-of-call ceiling
(`MIN_TURNS_BEFORE_END=3` floor, `MAX_TURNS=8` hard cap regardless of what the LLM signals) — the
state machine decides, the LLM only suggests, matching doc 03's stated principle.
`services/demo_conversation_service.py` orchestrates one fixed demo account/location/department
(created once, reused) with a fresh patient/visit/call every "Start Demo Call"; reuses the existing
`calls`/`transcripts`/`call_events` tables and schema unchanged. Real `LLMAdapter` implementations
for Gemini (`gemini-3.8-flash` default) and OpenAI (`gpt-6-sol` default) — the only two adapters
this MVP needs, since STT/TTS run entirely in the browser via the Web Speech API, not through
Deepgram/Cartesia. `require_demo_mode()` (`api/deps.py`) 404s every `/api/v1/demo/*` route unless
`DEMO_MODE=true` and `app_env != production`; `validate_startup()` additionally refuses to boot
with demo mode on in production (belt-and-suspenders, `PFA-SYS-010`).

Three real bugs were found and fixed by actually exercising the LLM call path end to end (not
assumed from SDK docs, which are ~8 months stale relative to this session and, separately, just
wrong about this specific case):
1. The Gemini SDK's newer Interactions API raises from a private, underscore-prefixed exception
   hierarchy (`google.genai._gaos.lib.compat_errors.*`) that shares no relationship with the public
   `google.genai.errors.ClientError`/`ServerError` classes the adapter was written against — every
   failure fell through uncaught. Fixed by duck-typing on `status_code` instead
   (`adapters/gemini/llm.py`'s `_map_gemini_error`). Also: Google's API returns HTTP 400
   `API_KEY_INVALID` for a bad key, not 401/403 — the adapter now treats that message as an auth
   failure regardless of status code.
2. `submit_turn` with a provider that has no *connected* saved key crashed with a raw `KeyError`
   out of `AdapterRegistry.get()` instead of a clean error. Fixed with an upfront
   `registry.has(provider)` check → `PFA-DEMO-008` (422, catalogued in doc 06).
3. `pybreaker` 1.4.1's `CircuitBreaker.call_async` is unusable without `tornado` installed (its
   `@gen.coroutine` wrapper references an undefined `gen` symbol — confirmed by direct testing;
   every call raised `NameError`, meaning **every real LLM call would have crashed**, valid key or
   not). `adapters/registry.py`'s new `call_with_breaker()` reimplements the same closed → open →
   half-open state machine natively against asyncio, verified by hand against the real library
   (trips after `fail_max` failures, fails fast while open, half-opens after `reset_timeout`,
   reopens on a failed trial). This was the first code in the whole repo to actually call
   `call_async` — Sprint 2+'s real STT/Telephony/TTS adapters will hit the same wall when they
   land; this fix benefits them too.

**Frontend** (`dashboard/src/app/demo/`): `page.tsx` (provider/model select, status badge, live
call with transcript + manual text fallback), `settings/page.tsx` (per-provider key + Save & Test,
hospital/agent/voice settings with a live check of which browser voices are actually available for
the selected gender+language), `debug/page.tsx` (full event timeline, failed step highlighted).
`hooks/useTurnController.ts` drives the `IDLE→...→LISTENING→PROCESSING→AGENT_SPEAKING→...→ENDED`
state machine over the Web Speech API; voice and the manual text fallback both funnel through the
same `submitAndRespond` path into the same backend engine.

**Verified**: 32 new automated tests (unit + real-Postgres integration, incl. every case in the
spec's language-switch script, the full malformed/failing-LLM retry-then-fallback path, and every
demo route 404ing with demo mode off) all pass; full regression run of the existing suite (193
tests) passes — in the course of which a pre-existing, unrelated test-isolation bug in
`test_ingestion_service.py` (an unscoped audit-log query that only failed when the full suite ran
together, never in isolation) was also found and fixed. `ruff`/`mypy --strict`/`lint-imports`/
`eslint`/`tsc` all clean. Manually verified against the real running docker-compose stack in a
real browser: full call start → Hinglish greeting → text-fallback turn → graceful fallback
response (using an intentionally invalid key, since a real key needs to be entered by the product
owner) → debug timeline showing the failed step clearly. Added a CORS policy (`main.py`, scoped to
`dashboard_base_url`, no credentials) since the browser now calls the API directly rather than
through a server-side proxy — nothing else in the existing auth/CORS story was touched.

**Known environment quirk**: Docker Desktop on Windows does not reliably forward file-change
events across the dashboard's bind mount to Next.js's dev-server watcher (confirmed: both new
route files and edits to existing ones were silently missed, twice, during this work) — fixed with
polling-based watching in `dashboard/next.config.mjs`. If dashboard edits still don't seem to take
effect, `docker restart pfa-dashboard-1` forces a fresh compile.

**Unified sidebar shell.** The four dashboard pages (`/demo`, `/demo/settings`, `/demo/debug`,
`/login`) moved under a new `app/(shell)/` route group with a persistent left sidebar
(`components/app-sidebar.tsx`) instead of ad hoc per-page text links — no URLs changed (route
groups don't add a path segment). `/` now redirects to `/demo` instead of `/login`, since the demo
is the actual working entry point right now. Found and fixed along the way: the polling
`watchOptions` fix above initially assigned `config.watchOptions` wholesale, which dropped
webpack's default `node_modules`/`.next` ignore list and caused a continuous Fast-Refresh rebuild
loop that was silently dropping click events on nav links — fixed by setting `ignored` explicitly.

**Pipeline Playground** (`/demo/playground`) — splits the live call's one combined LLM call into
seven independently-triggerable pipeline stages (language detection, topic extraction, language
lock, topic tracking, should-end judgment, end-of-call ceiling, response generation), each showing
its own input/output and, for the four LLM-backed stages, a per-stage provider+model choice so
different models can be compared stage by stage. Entirely new, parallel code
(`services/demo_playground_schemas.py`, `demo_playground_prompts.py`, `demo_playground_service.py`,
7 new routes in `api/v1/demo.py`) — the live call's own prompt/schema/service files are untouched,
and the Playground writes nothing to the database (stateless, and doesn't affect what the live call
actually uses). Unlike the live call, a Playground run never retries or falls back on a bad model
response — surfacing the failure clearly is the point for a tool built to compare models.

Building and testing this surfaced a real, previously-undetected bug: `AdapterAuthError`/
`AdapterBadResponse`/`AdapterTimeout` all inherited `DependencyError`'s blanket `http_status = 503`
instead of the specific statuses doc 06 documents for their `PFA-DEMO-00x` codes (401/502/504).
Every existing call site that could raise one also caught it internally before it reached the HTTP
layer (the live call's retry-then-fallback, `save_provider_key`'s try/except), so the wrong status
was never actually observed until the Playground — the first code path to let one of these
exceptions propagate all the way to a real response — hit it immediately. Fixed in `core/errors.py`
with a regression test (`test_adapter_error_http_status_mapping`) so it can't silently regress again.

**Call latency investigation.** A real demo call took 83+ seconds for one turn, then the next
failed outright — traced by hand (real timed calls against the actual API, not guessed) to two
compounding causes, not just "the model is slow": (1) `google-genai`'s default retry config
(`"attempt-count-backoff"`, `max_retries=4`, no overall elapsed-time cap for that strategy) retries
408/409/429/5xx and connection errors up to 5 total attempts, each able to take the full per-call
timeout — verified a single rate-limited call taking 180+ seconds to even fail, despite an explicit
`timeout=10.0`, since that parameter bounds one HTTP request, not the SDK's retry-and-backoff loop
wrapping it; (2) the configured model, `gemini-3.8-flash`, is free-tier-capped at **20 requests/day**
and that cap was already exhausted from same-day testing. `gemini-3.5-flash-lite` has its own
separate quota and answered consistently in 4-5s across repeated real calls with no rate-limiting.
Also found in the same pass: `gemini-2.5-flash` (still offered in `_MODEL_CHOICES`) is confirmed
dead for new API keys (404, "no longer available to new users") — removed from the dropdown
entirely rather than left as a guaranteed-broken option.

Fixed: `adapters/gemini/llm.py` now constructs `genai.Client` with retries disabled
(`_NO_RETRY_HTTP_OPTIONS`), so retry/fallback decisions live entirely in
`_call_llm_with_retry` (which already existed and actually respects a wall-clock ceiling); 429
responses now map to `AdapterRateLimited` (new code `PFA-DEMO-009`, 429 — doc 06 updated) instead
of the generic `AdapterBadResponse`, so a rate-limit shows up distinctly in the debug timeline
rather than looking like a generic bad response; `_LLM_TIMEOUT_S` lowered from 20s to 12s in both
`demo_conversation_service.py` and `demo_playground_service.py` (real latency is 4-5s — 12s gives
headroom without leaving a patient waiting ~40s across two attempts before a fallback, matching the
old 20s ceiling); `_MODEL_CHOICES` reordered with `gemini-3.5-flash-lite` first as the recommended
default; the already-configured demo Gemini credential's saved model was switched to it directly.
Verified end to end after the fix: a real call turn (real Gemini call, real DB writes, real
response) completed in **5.8 seconds**, full regression suite (211 tests) still green.

**Conversation quality pass.** Ran 3 full multi-turn conversations (14 turns) through the real live
call pipeline (not the Playground's separate prompt — this exercised `demo_prompts.py`, the actual
production prompt) covering multi-topic mixed praise/complaint, vague answers, an explicit language
switch, and a symptom mention. Found four real, reproducible issues in the actual model output (not
guessed):
1. An explicit English closing signal ("That's all, thank you") wasn't recognized as end-of-call —
   the agent kept asking another question — while the Hindi equivalent ("Bas itna hi tha") *was*
   caught correctly elsewhere. Inconsistent close-signal handling was the most serious finding.
2. The model invented an answer to a question the patient never actually addressed ("Bas itna hi
   tha, aur kuch nahi" got interpreted as "cleanliness was fine", though cleanliness was never
   mentioned).
3. A bare "Haan" (yes) to an ambiguous question got inflated into a specific claim ("doctor was
   good") the patient never made.
4. Mixed positive+negative feedback in one message only got acknowledged for the complaint half,
   silently dropping the positive part.

Fixed by adding explicit rules (with bilingual examples) to `demo_prompts.py`'s
`SYSTEM_PROMPT_HEADER` for all four, then re-ran the exact same conversations to confirm — all four
now correctly handled. Re-verification surfaced a fifth issue in the same pass: a short Roman-script
Hinglish reply ("Theek tha") was misclassified as `detected_language: "en"`, locking the rest of
that conversation to English even though the patient was speaking Hindi/Hinglish throughout — the
schema's field description and the prompt only ever said what "en" vs "hi/hinglish" *means*, never
that Hindi/Hinglish written in Roman script (no Devanagari) still counts as hi/hinglish, not
English. Fixed in both `demo_llm_schema.py`'s field description and the system prompt (and mirrored
in the Playground's parallel `demo_playground_schemas.py`/`demo_playground_prompts.py` for
consistency, though that's separate code and not itself under test here); re-verified with two more
full conversations designed to stress exactly this case — all correctly classified as hi/hinglish
afterward. Full regression suite (211 tests) and lint/mypy stayed green throughout, since these were
prompt-text and field-description changes only, no logic changes.

**Not built** (explicitly out of scope for this MVP, per the spec): Part-2 real-time
LiveKit/Deepgram/Cartesia voice transport, production telephony, analytics/reporting, barge-in/
streaming. The conversation engine (`domain/conversation_language.py`,
`domain/conversation_topics.py`, `services/demo_conversation_service.py`) was deliberately kept
independent of the browser/transport layer so it survives that transition unchanged.

### PRD v2 — Conversation Graph, Safety Layer & Scenario Harness (branch `demo-mvp`)

Replaces the free-form demo loop above with a node-graph engine: fixed nodes, the LLM proposes
within a node, deterministic code owns every transition and safety decision. Full plan/decisions in
the PRD (`20940476-PRD_PFA_Conversation_Graph_and_Safety_v2.md`, supplied out-of-repo); this log
covers what's actually built and verified so far.

**Phase 2 (engine core) + Phase 3 (safety) — done.** Pure `domain/conversation_graph/` package:
`graph.py` (14-node state machine + legal-edge table), `state.py` (call state + topic/severity/
register/safety enums), `policy.py` (opt-out/wants-human/repeat-request pre-checks), `safety.py`
(lexicon scan OR-merged with the LLM's own safety flag), `severity.py` (S0-S4 resolution +
escalation routing), `scripts.py` + `assets/scripts.yaml` (every FIXED line, gendered, in Hinglish/
Devanagari/English), `normalizer.py` (numbers/dates/times/phone → spoken words), `guards.py` (the 6
output guards), `repair.py` (repeat-question/silence counters). 351 unit tests.

Found and fixed a real bug during verification: the safety lexicon used `\b` word boundaries, which
rely on Python's `\w` and exclude Devanagari combining vowel signs (category Mc — e.g. the ा matra
in "मरना"). `\b` was silently splitting mid-word for any Hindi phrase ending in a matra, so several
seeded self_harm/threat phrases never matched. Fixed with whitespace-based boundaries
(`(?<!\S)...(?!\S)` instead of `\b...\b`) in `safety.py`.

**Phase 4 (LLM integration) — done.** 9 per-node prompt files (`assets/node_prompts/*.md`,
one per node where the LLM genuinely interprets patient intent — pure-FIXED utility/terminal nodes
never call the LLM), `services/pfa_call_prompts.py` (system instruction + input transcript
construction), `services/pfa_call_service.py` (the full per-turn orchestrator: safety pre-scan,
policy pre-checks, LLM call with retry+fallback, severity-gate resolution, illegal-transition
rejection, FIXED-vs-LLM reply composition). Registered `"pfa_node_turn" -> NodeContract` in both the
Gemini and OpenAI adapters.

A second real bug surfaced here: the length guard was truncating FIXED safety-escalation scripts
and the consent disclosure line — both legitimately exceed the generic 25/30-word turn budget by
design (the PRD's own emergency-number lines, Tele-MANAS helpline number, and consent text). The
PRD's word limit is specified for LLM-*generated* replies, not vetted FIXED copy, so
`pfa_call_service._finalize`'s length enforcement now defaults to off and is opted back into only
the 3 call sites that carry genuine LLM-authored text (readback summary, fresh-complaint
acknowledgement, plain LLM-node replies) — every other guard (promo/medical-advice/pre-identity
disclosure) still always runs regardless.

12 new mock-LLM integration tests (queued stub adapter, no database) — full happy path, opt-out/
wants-human/repeat-request, safety escalation via both the keyword and LLM-flag paths, S3
auto-advance, illegal-transition rejection, silence handling, LLM-contract-failure fallback, guard
truncation. Then a real Gemini smoke call (`gemini-3.5-flash-lite`) through all 9 node prompts:
first pass 6/9 (3 timed out — transient free-tier latency, not a prompt problem, confirmed by
immediately retrying those 3 successfully). All 9 produced coherent, well-formed `NodeContract`
JSON. Notably, the live model hallucinated two invalid node names (`visit_experience_rating`,
`consent` instead of the real `open_experience`/`purpose_consent_time`) — real-world confirmation
that `graph.next_node()`'s illegal-transition rejection is load-bearing, not just a theoretical
safety net. 369/369 tests green across the whole conversation-graph suite throughout; ruff/
mypy --strict/lint-imports clean.

Known, documented simplifications versus the PRD's literal wording (see `pfa_call_service.py`'s
module docstring for the full reasoning): `CALLBACK` is a one-shot exit rather than the PRD's
two-turn "ask when → confirm slot" (matches `graph.py`'s already-tested terminal-node model, which
has no self-loop for it); the `ESCALATE_URGENT` medical/self-harm follow-up ("would you like a
callback now?") is answered with a small deterministic yes/no check instead of a tenth LLM prompt
file, since the call proceeds to `CLOSE` either way.

**Not yet built:** migration `0016` and real persistence (`pfa_call_state`, results/escalations
tables — currently `process_turn`/`start_turn` are pure functions with no DB session), new API
endpoints, resume-after-restart, dashboard wiring (patient form, results/escalations pages, debug
additions), the 40-scenario harness, CSV-ingested-visit call start, README/final report.

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
