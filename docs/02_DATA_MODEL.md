# 02 — Data Model

PostgreSQL 16. All PKs are UUIDv7. All timestamps `timestamptz` in UTC. Every tenant table has
`account_id` and every query goes through a repository that **requires** `account_id` (tenant isolation
enforced in code + Postgres Row-Level Security, see §5).

## 1. Enums

```sql
CREATE TYPE account_status      AS ENUM ('onboarding','live','paused','offboarded');
CREATE TYPE visit_type          AS ENUM ('outpatient','diagnostic');           -- MVP scope
CREATE TYPE eligibility_status  AS ENUM ('pending','eligible','suppressed','review');
CREATE TYPE suppression_reason  AS ENUM (
  'minor','invalid_number','opt_out','dnd','duplicate_encounter','already_called_visit',
  'frequency_cap','stale_visit','shared_number_review','consent_declined_visit',
  'out_of_scope_visit_type','missing_required_field','deleted_patient');
CREATE TYPE call_status AS ENUM (
  'queued','dialing','ringing','answered','in_progress','completed','partial',
  'abandoned_pre_consent','consent_declined','voicemail','no_answer','busy',
  'failed_telephony','failed_system','cancelled');
CREATE TYPE consent_state       AS ENUM ('not_asked','granted','declined','withdrawn','granted_unrecorded');
CREATE TYPE respondent_type     AS ENUM ('patient','proxy','unknown');
CREATE TYPE campaign_type       AS ENUM ('service_feedback','promotional');     -- promotional disabled in MVP
CREATE TYPE sentiment           AS ENUM ('negative','neutral','positive');
CREATE TYPE urgency             AS ENUM ('routine','service_failure','safety_concern');
CREATE TYPE case_status         AS ENUM ('open','acknowledged','assigned','in_progress',
                                         'resolved','closed','reopened','merged','invalid');
CREATE TYPE case_priority       AS ENUM ('p1','p2','p3');   -- p1=safety, p2=service_failure, p3=manual/other
CREATE TYPE user_role           AS ENUM ('super_admin','admin','quality','dept_owner','read_only');
CREATE TYPE speaker             AS ENUM ('agent','patient','system');
CREATE TYPE deletion_scope      AS ENUM ('patient','account');
CREATE TYPE deletion_status     AS ENUM ('requested','approved','running','completed','failed','rejected');
CREATE TYPE ingestion_status    AS ENUM ('received','validating','validated','failed','processed');
```

## 2. Tables (DDL)

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------- Tenancy ----------
CREATE TABLE accounts (
  account_id            uuid PRIMARY KEY,
  name                  text NOT NULL,
  display_name_tts      text NOT NULL,                 -- how the agent says the hospital name
  tier                  text NOT NULL DEFAULT 'standard',
  status                account_status NOT NULL DEFAULT 'onboarding',
  timezone              text NOT NULL DEFAULT 'Asia/Kolkata',
  contact_window_start  time NOT NULL DEFAULT '10:00',
  contact_window_end    time NOT NULL DEFAULT '19:00',
  contact_days          smallint[] NOT NULL DEFAULT '{1,2,3,4,5,6}',  -- ISO weekday; Sunday excluded by default
  holidays              date[] NOT NULL DEFAULT '{}',
  max_concurrent_calls  int NOT NULL DEFAULT 10 CHECK (max_concurrent_calls BETWEEN 1 AND 200),
  daily_call_cap        int NOT NULL DEFAULT 500,
  survey_version_id     uuid,
  primary_metric        text NOT NULL DEFAULT 'csat' CHECK (primary_metric IN ('nps','csat')),
  languages             text[] NOT NULL DEFAULT '{en,hi}',
  allow_proxy_feedback  boolean NOT NULL DEFAULT false,
  recency_window_hours  int NOT NULL DEFAULT 72,
  dedupe_window_days    int NOT NULL DEFAULT 7,
  frequency_cap_days    int NOT NULL DEFAULT 30,
  frequency_cap_count   int NOT NULL DEFAULT 1,
  shared_number_threshold int NOT NULL DEFAULT 3,
  retention_policy      jsonb NOT NULL,     -- see §4
  sla_config            jsonb NOT NULL,     -- see §4
  emergency_number      text NOT NULL DEFAULT '112',
  hospital_urgent_line  text,               -- E.164, spoken in safety path
  caller_id_e164        text NOT NULL,      -- registered CLI
  default_case_owner_id uuid,               -- must be set before status=live
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE locations (
  location_id  uuid PRIMARY KEY,
  account_id   uuid NOT NULL REFERENCES accounts,
  external_location_id text NOT NULL,
  name         text NOT NULL,
  address      text,
  timezone     text,                          -- overrides account tz if set
  UNIQUE (account_id, external_location_id)
);

CREATE TABLE departments (
  department_id uuid PRIMARY KEY,
  account_id    uuid NOT NULL REFERENCES accounts,
  code          text NOT NULL,                -- normalised key from CSV
  name          text NOT NULL,
  tts_name_en   text, tts_name_hi text,       -- pronunciation overrides
  owner_user_id uuid,                         -- default case owner for this dept
  UNIQUE (account_id, code)
);

CREATE TABLE users (
  user_id       uuid PRIMARY KEY,
  account_id    uuid REFERENCES accounts,     -- NULL only for super_admin
  email         citext NOT NULL UNIQUE,
  name          text NOT NULL,
  role          user_role NOT NULL,
  password_hash text,                          -- argon2id; NULL when SSO (Phase 2)
  mfa_secret_enc bytea,
  is_active     boolean NOT NULL DEFAULT true,
  location_ids  uuid[] NOT NULL DEFAULT '{}',  -- empty = all
  department_ids uuid[] NOT NULL DEFAULT '{}', -- dept_owner scope
  last_login_at timestamptz,
  failed_logins int NOT NULL DEFAULT 0,
  locked_until  timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- Survey config ----------
CREATE TABLE survey_versions (
  survey_version_id uuid PRIMARY KEY,
  account_id  uuid NOT NULL REFERENCES accounts,
  version     int NOT NULL,
  definition  jsonb NOT NULL,       -- questions, dimensions, scale; schema in doc 03 §5
  taxonomy    jsonb NOT NULL,       -- reason codes; default from domain/taxonomy.py
  is_active   boolean NOT NULL DEFAULT false,
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, version)
);

-- ---------- Ingestion ----------
CREATE TABLE ingestion_batches (
  batch_id     uuid PRIMARY KEY,
  account_id   uuid NOT NULL REFERENCES accounts,
  source       text NOT NULL CHECK (source IN ('sftp','upload')),
  filename     text NOT NULL,
  sha256       text NOT NULL,
  status       ingestion_status NOT NULL DEFAULT 'received',
  rows_total   int, rows_valid int, rows_rejected int,
  uploaded_by  uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  UNIQUE (account_id, sha256)                   -- same file twice = rejected (PFA-ING-006)
);

CREATE TABLE ingestion_row_errors (
  id         bigserial PRIMARY KEY,
  batch_id   uuid NOT NULL REFERENCES ingestion_batches ON DELETE CASCADE,
  row_number int NOT NULL,
  field      text,
  error_code text NOT NULL,                     -- PFA-ING-xxx
  message    text NOT NULL                      -- never contains the raw phone number
);

-- ---------- Patients & visits ----------
CREATE TABLE patients (
  patient_ref_id      uuid PRIMARY KEY,
  account_id          uuid NOT NULL REFERENCES accounts,
  external_patient_id text NOT NULL,
  phone_hash          bytea NOT NULL,           -- HMAC-SHA256(pepper, e164)
  phone_e164_enc      bytea NOT NULL,           -- AES-256-GCM envelope (see doc 07)
  phone_last4         char(4) NOT NULL,         -- for UI display only
  preferred_language  text,
  opt_out             boolean NOT NULL DEFAULT false,
  opt_out_at          timestamptz,
  deleted_at          timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, external_patient_id)
);
CREATE INDEX ON patients (account_id, phone_hash);

CREATE TABLE visits (
  visit_id        uuid PRIMARY KEY,
  account_id      uuid NOT NULL REFERENCES accounts,
  location_id     uuid NOT NULL REFERENCES locations,
  patient_ref_id  uuid NOT NULL REFERENCES patients,
  batch_id        uuid REFERENCES ingestion_batches,
  external_visit_key text NOT NULL,             -- hash(external_patient_id, visit_date, dept)
  visit_date      date NOT NULL,
  visit_type      visit_type NOT NULL,
  department_id   uuid NOT NULL REFERENCES departments,
  doctor_name     text,
  patient_age     smallint NOT NULL CHECK (patient_age BETWEEN 0 AND 130),
  consent_flag    boolean,
  eligibility_status eligibility_status NOT NULL DEFAULT 'pending',
  suppression_reason suppression_reason,
  eligibility_evaluated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (account_id, external_visit_key)
);
CREATE INDEX ON visits (account_id, eligibility_status, visit_date);

-- ---------- Calls ----------
CREATE TABLE calls (
  call_id           uuid PRIMARY KEY,
  account_id        uuid NOT NULL REFERENCES accounts,
  visit_id          uuid NOT NULL REFERENCES visits,
  campaign_type     campaign_type NOT NULL DEFAULT 'service_feedback',
  attempt_no        smallint NOT NULL CHECK (attempt_no BETWEEN 1 AND 3),
  scheduled_at      timestamptz NOT NULL,
  started_at        timestamptz,
  answered_at       timestamptz,
  ended_at          timestamptz,
  status            call_status NOT NULL DEFAULT 'queued',
  end_reason        text,                        -- catalogued code
  provider_call_id  text,
  consent_state     consent_state NOT NULL DEFAULT 'not_asked',
  consent_at        timestamptz,
  respondent        respondent_type NOT NULL DEFAULT 'unknown',
  languages_used    text[] NOT NULL DEFAULT '{}',
  duration_sec      int,
  billable_sec      int,
  turn_count        int NOT NULL DEFAULT 0,
  survey_version_id uuid REFERENCES survey_versions,
  state_snapshot    jsonb,                        -- latest call_state (doc 03 §6)
  safety_flag       boolean NOT NULL DEFAULT false,
  needs_human_review boolean NOT NULL DEFAULT false,
  recording_uri     text,
  recording_retention_until timestamptz,
  cost_breakdown    jsonb,                        -- paise per component (doc 09)
  cost_total_paise  int,
  prompt_versions   jsonb,                        -- prompt ids+versions used (audit)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (visit_id, attempt_no)
);
CREATE INDEX ON calls (account_id, status, scheduled_at);
CREATE UNIQUE INDEX one_active_call_per_visit ON calls (visit_id)
  WHERE status IN ('queued','dialing','ringing','answered','in_progress');

CREATE TABLE call_events (           -- append-only state/latency log for replay
  id        bigserial PRIMARY KEY,
  call_id   uuid NOT NULL REFERENCES calls,
  ts        timestamptz NOT NULL DEFAULT now(),
  type      text NOT NULL,           -- e.g. state.transition, adapter.call, safety.trigger
  data      jsonb NOT NULL
);
CREATE INDEX ON call_events (call_id, ts);

CREATE TABLE transcripts (
  transcript_id  uuid PRIMARY KEY,
  call_id        uuid NOT NULL REFERENCES calls ON DELETE CASCADE,
  turn_index     int NOT NULL,
  speaker        speaker NOT NULL,
  text_enc       bytea NOT NULL,     -- encrypted at app layer
  start_ms       int NOT NULL,
  end_ms         int NOT NULL,
  stt_confidence real,
  language       text,
  retention_until timestamptz NOT NULL,
  UNIQUE (call_id, turn_index, speaker)
);

CREATE TABLE survey_responses (
  response_id    uuid PRIMARY KEY,
  call_id        uuid NOT NULL REFERENCES calls ON DELETE CASCADE,
  field_key      text NOT NULL,       -- e.g. overall, doctor, billing, wait_time
  field_value    jsonb NOT NULL,      -- {"score": 3} or {"text": "..."}
  extraction_confidence real NOT NULL,
  source_turn_index int NOT NULL,
  method         text NOT NULL CHECK (method IN ('deterministic','llm')),
  UNIQUE (call_id, field_key)
);

CREATE TABLE complaints (
  complaint_id  uuid PRIMARY KEY,
  account_id    uuid NOT NULL REFERENCES accounts,
  call_id       uuid NOT NULL REFERENCES calls,
  visit_id      uuid NOT NULL REFERENCES visits,
  department_id uuid REFERENCES departments,
  reason_codes  text[] NOT NULL,
  sentiment     sentiment NOT NULL,
  sentiment_conf real NOT NULL,
  urgency       urgency NOT NULL,
  urgency_conf  real NOT NULL,
  urgency_source text NOT NULL CHECK (urgency_source IN ('rule','llm','rule+llm','human')),
  summary       text NOT NULL,          -- 1–2 lines, no clinical inference
  verbatim_enc  bytea NOT NULL,
  verbatim_start_ms int NOT NULL,
  verbatim_end_ms   int NOT NULL,
  retention_until timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (verbatim_end_ms > verbatim_start_ms)
);

-- ---------- Cases ----------
CREATE TABLE cases (
  case_id        uuid PRIMARY KEY,
  account_id     uuid NOT NULL REFERENCES accounts,
  complaint_id   uuid NOT NULL REFERENCES complaints,
  location_id    uuid NOT NULL REFERENCES locations,
  department_id  uuid REFERENCES departments,
  status         case_status NOT NULL DEFAULT 'open',
  priority       case_priority NOT NULL,
  assigned_to    uuid REFERENCES users,
  acknowledged_at timestamptz,
  resolved_at    timestamptz,
  closed_at      timestamptz,
  ack_due_at     timestamptz NOT NULL,
  resolve_due_at timestamptz,
  ack_breached   boolean NOT NULL DEFAULT false,
  resolve_breached boolean NOT NULL DEFAULT false,
  resolution_note text,
  merged_into_case_id uuid REFERENCES cases,
  reopen_count   int NOT NULL DEFAULT 0,
  version        int NOT NULL DEFAULT 1,       -- optimistic locking
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'closed' OR resolution_note IS NOT NULL),
  CHECK (status <> 'merged' OR merged_into_case_id IS NOT NULL)
);
CREATE INDEX ON cases (account_id, status, priority, ack_due_at);

CREATE TABLE case_events (
  event_id    uuid PRIMARY KEY,
  case_id     uuid NOT NULL REFERENCES cases,
  actor_type  text NOT NULL CHECK (actor_type IN ('user','system')),
  actor_id    uuid,
  from_status case_status,
  to_status   case_status,
  action      text NOT NULL,          -- create, assign, acknowledge, note, resolve, close, reopen, merge, sla_breach
  note        text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- Suppression, audit, deletion ----------
CREATE TABLE suppression_list (
  entry_id    uuid PRIMARY KEY,
  account_id  uuid REFERENCES accounts,        -- NULL = platform-wide (e.g. NCPR)
  phone_hash  bytea NOT NULL,
  reason      text NOT NULL CHECK (reason IN ('opt_out','dnd','consent_declined','manual','deleted')),
  source      text NOT NULL,                    -- call, dashboard, ncpr_sync, deletion
  campaign_type campaign_type,                  -- NULL = all campaigns
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz                       -- NULL = permanent
);
CREATE INDEX ON suppression_list (phone_hash);

CREATE TABLE audit_log (                         -- append-only; UPDATE/DELETE revoked
  log_id      bigserial PRIMARY KEY,
  account_id  uuid,
  actor_type  text NOT NULL,
  actor_id    uuid,
  action      text NOT NULL,                     -- e.g. case.transition, transcript.view, audio.play
  entity_type text NOT NULL,
  entity_id   uuid,
  before_json jsonb,
  after_json  jsonb,
  ip          inet,
  user_agent  text,
  request_id  text,
  prev_hash   bytea,                             -- hash chain for tamper evidence
  row_hash    bytea NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE deletion_requests (
  request_id   uuid PRIMARY KEY,
  account_id   uuid NOT NULL REFERENCES accounts,
  scope        deletion_scope NOT NULL,
  patient_ref_id uuid,
  requested_by uuid NOT NULL,
  approved_by  uuid,
  status       deletion_status NOT NULL DEFAULT 'requested',
  reason       text NOT NULL,
  due_at       timestamptz NOT NULL,             -- SLA (default 7 days)
  completed_at timestamptz,
  report       jsonb                             -- counts deleted per entity
);

CREATE TABLE pending_safety_cases (             -- fallback if P1 case insert fails in-call (PFA-SAF-004)
  id          bigserial PRIMARY KEY,
  account_id  uuid NOT NULL,
  call_id     uuid NOT NULL,
  payload     jsonb NOT NULL,                    -- trigger group, rule id, turn index (no raw text)
  attempts    int NOT NULL DEFAULT 0,
  resolved_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feature_flags (
  account_id  uuid NOT NULL REFERENCES accounts,
  flag        text NOT NULL,                     -- llm_paraphrase, warm_transfer, keypad_fallback, proxy_feedback
  enabled     boolean NOT NULL DEFAULT false,
  PRIMARY KEY (account_id, flag)
);

CREATE TABLE cost_rates (                        -- versioned unit prices for telemetry
  id          uuid PRIMARY KEY,
  component   text NOT NULL,                     -- telephony, stt, llm_in, llm_out, tts, infra
  provider    text NOT NULL,
  unit        text NOT NULL,                     -- per_min, per_1k_tokens, per_1k_chars
  paise_per_unit numeric(12,4) NOT NULL,
  effective_from timestamptz NOT NULL
);
```

## 3. Integrity rules implemented in code

| Rule | Where |
|---|---|
| One active call per visit | partial unique index `one_active_call_per_visit` |
| Max 3 attempts per visit | `CHECK attempt_no BETWEEN 1 AND 3` + `retry_policy.py` |
| Closed case needs resolution note | CHECK + `case_lifecycle.py` guard |
| Account cannot go `live` without `default_case_owner_id` and caller ID | service guard `PFA-ACC-003` |
| Consent before survey rows | `survey_responses` insert guarded: service rejects if `calls.consent_state` ∉ {granted, granted_unrecorded} (`PFA-CNS-004`) |
| Audit log append-only | DB roles have no UPDATE/DELETE on `audit_log` (SELECT + INSERT only — SELECT is needed so `audit_service.record()` can read the chain tail it hashes against, and so it can be viewed at all; see migration 0011) |

## 4. JSON config shapes

```jsonc
// accounts.retention_policy
{
  "audio_days": 30,               // OPEN QUESTION #4 — default until decided
  "transcript_days": 180,
  "verbatim_days": 365,           // complaints needed for accreditation evidence
  "call_metadata_days": 730,
  "abandoned_pre_consent_audio": 0,
  "consent_declined_audio": 0
}
// accounts.sla_config  (hours)
{
  "p1": {"ack": 1,  "resolve": 24},
  "p2": {"ack": 24, "resolve": 72},
  "p3": {"ack": 72, "resolve": null},
  "business_hours_only": false,
  "breach_notify": ["assignee","quality_lead"]
}
```

## 5. Tenant isolation

- Postgres RLS on all tenant tables: `USING (account_id = current_setting('app.account_id')::uuid)`.
  The API sets `SET LOCAL app.account_id` per request transaction from the authenticated user.
  `super_admin` uses a separate DB role with `BYPASSRLS`, and every such access is audited.
- Repositories take `account_id` as a mandatory argument (belt and braces).

## 6. Migrations

Order: `0001_enums` → `0002_tenancy` → `0003_survey` → `0004_ingestion` → `0005_patients_visits` →
`0006_calls_transcripts` → `0007_complaints_cases` → `0008_suppression_audit_deletion` →
`0009_cost` → `0010_rls_policies` → `0011_grants`.
Every migration has a working `downgrade()`, tested in CI (`upgrade head → downgrade base → upgrade head`).

## 7. Retention mapping

| Artefact | Field | Purged by |
|---|---|---|
| Audio | `calls.recording_retention_until` | `retention.purge_audio` (hourly) |
| Transcripts | `transcripts.retention_until` | `retention.purge_transcripts` (daily) |
| Verbatims | `complaints.retention_until` | `retention.purge_verbatims` — replaces `verbatim_enc` with tombstone, keeps structured fields |
| Call metadata | `calls.created_at + call_metadata_days` | `retention.purge_calls` (daily) — anonymise visit link |
| Audit log | never purged by tenant policy (legal hold); account offboarding exports then deletes after contract term |
