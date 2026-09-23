# 10 — Deployment & Operations

## 1. Environments

| Env | Purpose | Telephony | Data | LLM/STT/TTS |
|---|---|---|---|---|
| `local` | Development | Fake adapter (no calls) | Synthetic seed | Fakes by default; real via flag |
| `ci` | Automated tests | Fake | Ephemeral testcontainers | Fakes (nightly: sandbox keys) |
| `staging` | Integration, demos, benchmarks | Real Plivo sub-account, **allowlist only** (`TEST_ALLOWLIST_E164`) | Synthetic + demo account | Real, non-retention settings |
| `production` | Pilots | Real, full compliance checks | Real patient data | Real |

Hosting: India region (e.g., Mumbai/Hyderabad) for DB, object storage, app, backups (OPEN QUESTION #9
for stricter residency). LiveKit: Cloud (fastest start) or self-hosted in the same region — decided by
pilot IT review; adapter/config supports both.

## 2. Local setup (`infra/docker-compose.yml`)

Services: `postgres:16`, `redis:7`, `api`, `worker` (all queues), `beat`, `agent`, `dashboard`,
`mailpit` (catch emails at :8025), `minio` (S3), `livekit-server` (dev mode), `otel-collector`
(optional profile), `grafana`+`prometheus` (optional profile).

```bash
cp .env.example .env
make up && make migrate && make seed
open http://localhost:3000      # dashboard  (admin@demo.local / printed on seed)
make sim SCENARIO=S12           # run a simulated emergency call end to end
```

## 3. `.env.example` (all settings documented)

```
APP_ENV=local
DATABASE_URL=postgresql+asyncpg://pfa:pfa@postgres:5432/pfa
REDIS_URL=redis://redis:6379/0
SECRET_KEY_ID=dev
JWT_PRIVATE_KEY_PATH=./dev-keys/jwt_ed25519
KMS_PROVIDER=local            # local|aws|gcp
LOCAL_KEK_BASE64=<dev only>
PHONE_HASH_PEPPER=<dev only>
TELEPHONY_PROVIDER=fake       # fake|plivo
PLIVO_AUTH_ID=
PLIVO_AUTH_TOKEN=
STT_PROVIDER=fake             # fake|deepgram
DEEPGRAM_API_KEY=
LLM_PROVIDER=fake             # fake|gemini
GEMINI_API_KEY=
LLM_MODEL_INCALL=gemini-flash
LLM_MODEL_POSTCALL=gemini-flash
TTS_PROVIDER=fake             # fake|cartesia
CARTESIA_API_KEY=
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret
S3_ENDPOINT=http://minio:9000
S3_BUCKET=pfa-audio
EMAIL_PROVIDER=smtp
SMTP_URL=smtp://mailpit:1025
TEST_ALLOWLIST_E164=          # comma list; REQUIRED outside production
PLATFORM_MAX_CONCURRENT_CALLS=50
DND_STRICT=true
PUBLIC_BASE_URL=http://localhost:8010
DASHBOARD_BASE_URL=http://localhost:3000
SENTRY_DSN=
```
Startup validation: in non-production, if `TELEPHONY_PROVIDER=plivo` and allowlist empty → refuse to
start (`PFA-SYS-010`). In production, fake providers → refuse to start.

## 4. CI/CD (GitHub Actions)

- `ci.yml` on PR: pipeline from doc 08 §11. Required checks block merge.
- `deploy-staging.yml` on main: build + sign images (cosign), push, run migrations (job), rolling deploy,
  smoke tests (health, login, sim call against fake telephony in staging, one allowlisted real call
  weekly).
- `deploy-prod.yml` manual approval, tag-based. Migrations must be **backward compatible**
  (expand → migrate → contract across two releases). Rollback = previous image tag; DB down-migrations
  only for failed expand steps.
- Feature flags (DB table `feature_flags`, per account): `llm_paraphrase`, `warm_transfer`,
  `keypad_fallback`, `proxy_feedback`.

## 5. Production topology & sizing

| Component | MVP size (100–500 calls/day/account, few accounts) |
|---|---|
| api | 2 replicas × 1 vCPU / 1 GB |
| worker | 2 replicas × 2 vCPU / 2 GB (queues split: `dial`+`notify` vs `ingest`+`postcall`+`maintenance`) |
| beat | 1 replica (leader lock in Redis) |
| agent | 2 servers × 4 vCPU / 8 GB (~10–25 jobs each) → ≥ 2× computed peak |
| dashboard | 2 replicas × 0.5 vCPU |
| postgres | managed, 2 vCPU / 8 GB, HA, PITR 7 days |
| redis | managed, 1 GB, replica |

Sizing check per account: `peak_concurrency = calls_per_hour × avg_minutes / 60`; example 300 calls in
2 h × 6 min → 15 → provision 30. Binding constraint is peak concurrency, not daily volume.

Backups: PITR + nightly logical dump (encrypted, India region); monthly restore drill logged.

## 6. Runbooks (`docs/runbooks/*.md`, one page each)

1. **Pause calling** (account or platform): Settings → Pause, or `make pause ACCOUNT=…`; verify
   `pfa_concurrent_calls` → 0 new.
2. **Safety case creation failed (PFA-SAF-004)**: check fallback table `pending_safety_cases`, run
   `scripts/replay_safety.py`, phone the account's quality lead directly with case details from the
   fallback record; post-incident review within 24 h.
3. **Compliance violation detected** (out-of-window, suppressed number, pre-consent question): pause
   platform dialing, preserve logs, identify affected calls via compliance query, notify account
   (fiduciary) within 24 h, root-cause + fix + test before resuming.
4. **Vendor outage** (breaker open): confirm on vendor status, dialing auto-halted; if > 2 h, notify
   affected accounts; resume when breaker closes; queued calls re-evaluated for window/recency.
5. **Data breach / suspected unauthorised access**: contain (revoke tokens, rotate keys), preserve
   evidence (audit log, access logs), assess scope (tenants, data categories, individuals), notify
   fiduciary hospitals within the DPA window with: what, when, data categories, likely consequences,
   mitigation, contact. Support hospitals' regulatory/patient notifications. Post-mortem.
6. **Deletion request stuck/failed**: inspect `deletion_requests.report`, rerun job (idempotent), verify
   counts, close with audit.
7. **SFTP file missing / rejected**: check poll logs, batch status, notify account admin with error codes.
8. **High latency**: check `pfa_turn_latency_seconds{segment}` to find the slow segment; switch voice/
   region/model via config; open vendor ticket.
9. **Cost anomaly**: compare breakdown by component; typical causes: retries storm, long calls,
   cache miss on audio, LLM invoked on deterministic turns.
10. **Retention purge failure**: rerun; S3 lifecycle is backstop; report if overdue > 24 h.

## 7. Pilot onboarding checklist (product-enforced where possible)

- [ ] Account created, timezone, contact window, holidays
- [ ] Caller ID provisioned and verified (Plivo India, DLT/registration confirmed — business)
- [ ] Locations + departments + department owners mapped
- [ ] **Named escalation owner** (default case owner) set — activation blocked otherwise
- [ ] Survey version configured, Hindi/regional text reviewed by native speaker + account
- [ ] Pronunciation dictionary: hospital, departments, top doctors
- [ ] Audio pre-rendered and listened to ("Play audio" in survey preview)
- [ ] SLA + retention policy agreed and set
- [ ] Users invited, MFA for admins
- [ ] SFTP key uploaded or first manual upload done; data-quality report reviewed with account
- [ ] 10 scripted test calls to staff phones (incl. emergency + clinical scenarios) passed
- [ ] Baseline metrics captured (existing SMS/paper/manual calling) for ROI comparison
- [ ] Account set `live`
