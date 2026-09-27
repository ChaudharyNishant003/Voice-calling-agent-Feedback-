# 06 — Error Handling & Message Catalogue

## 1. Principles

1. **Every failure has a code.** Format `PFA-<AREA>-<NNN>`. Codes are stable forever; never reuse.
2. **Fail safe, not silent.** When a component fails mid-call, the patient hears a calm, fixed message
   and the call ends or falls back; data captured so far is kept; a human review flag is set if safety
   could be involved.
3. **Deterministic fallbacks beat retries** in real time. Retry only where the latency budget allows.
4. **Bounded retries everywhere** — each retry loop declares `max_attempts` and backoff.
5. **User-facing text ≠ log text.** Messages never include stack traces, PII, vendor names, or internals.
6. **Errors are observable:** every raised `PFAError` increments `pfa_errors_total{code}` and logs once
   at the boundary (not at every layer).

## 2. Exception hierarchy (`core/errors.py`)

```python
class PFAError(Exception):
    code: str; http_status: int = 500; user_message_key: str; retryable: bool = False
    def __init__(self, code: str, *, details: dict | None = None, cause: Exception | None = None): ...

class ValidationError(PFAError):     http_status = 422
class AuthError(PFAError):           http_status = 401
class PermissionError_(PFAError):    http_status = 403
class NotFoundError(PFAError):       http_status = 404
class ConflictError(PFAError):       http_status = 409
class RateLimitError(PFAError):      http_status = 429
class DependencyError(PFAError):     http_status = 503; retryable = True
class ComplianceBlock(PFAError):     http_status = 409   # action blocked by a compliance rule
class AdapterError(DependencyError): ...                 # base for all vendor failures
class AdapterTimeout(AdapterError): ...
class AdapterBadResponse(AdapterError): ...
class AdapterAuthError(AdapterError): retryable = False
class AdapterRateLimited(AdapterError): ...
```
Adapters translate vendor exceptions into these. FastAPI exception handler renders the envelope
(doc 04 §1). Celery tasks use a decorator that maps exceptions to retry/no-retry per `retryable`.

## 3. Retry & timeout policy

| Operation | Timeout | Max attempts | Backoff | On final failure |
|---|---|---|---|---|
| Telephony `place_call` | 5 s | 2 | 2 s | call `failed_telephony`, schedule per retry policy |
| Telephony `hangup` | 3 s | 3 | 1 s | log `PFA-TEL-004`, rely on provider timeout |
| STT stream open | 3 s | 2 | 0.5 s | play `system_error`, end call, retry once later |
| STT stream drop mid-call | — | 1 reconnect | immediate | if reconnect fails → `system_error` close, `partial` |
| LLM in-call (interpret/probe) | 1.5 s | 1 (no retry in-call) | — | deterministic fallback (§5) |
| LLM post-call extract | 20 s | 2 | 5 s, 30 s | `needs_human_review`, p3 case if negatives |
| LLM malformed JSON | — | 1 re-ask (stricter) | — | fallback as above |
| TTS stream | 1.2 s to first byte | provider → fallback voice → fallback provider → cached generic | — | cached `system_error` clip |
| Email send | 10 s | 5 | 1, 5, 30 min, 2 h, 6 h | dead-letter + in-app banner "Some alerts could not be emailed" |
| Webhook out (Phase 2) | 10 s | 6 | see doc 04 §11 | dead-letter |
| DB transaction (serialization/deadlock) | 5 s | 3 | 50/100/200 ms jitter | raise `PFA-SYS-002` |
| S3 put (audio) | 30 s | 3 | 2, 10, 30 s | keep in local spool ≤ 1 h, alert |
| SFTP poll | 30 s | next scheduled poll | — | alert after 3 consecutive failures |

Circuit breaker per adapter (`pybreaker`-style in `adapters/registry.py`): open after 5 failures in 30 s,
half-open after 30 s. While STT/TTS/telephony breaker is open, **the dial service stops placing new
calls** for affected accounts (`PFA-ORC-007`) — don't start calls we can't finish.

## 4. Error catalogue

Columns: code · HTTP · log level · meaning · user message (UI key `err.<code>`) · handling.

### 4.1 Auth & users (`AUTH`, `USR`)
| Code | HTTP | Level | Meaning | User message | Handling |
|---|---|---|---|---|---|
| PFA-AUTH-001 | 401 | info | Bad credentials | "Email or password is incorrect." | count failure |
| PFA-AUTH-002 | 401 | info | Session expired | "Your session has expired. Please sign in again." | redirect to login, keep return URL |
| PFA-AUTH-003 | 423→401 | warn | Account locked | "Too many attempts. Try again in 15 minutes." | lock 15 min, email user |
| PFA-AUTH-004 | 401 | info | MFA code invalid | "That code didn't work. Check your authenticator app and try again." | 5 tries then lock |
| PFA-AUTH-005 | 401 | warn | CSRF missing/invalid | "Your session needs refreshing. Please reload the page." | — |
| PFA-AUTH-006 | 400 | info | Reset token invalid/expired | "This link has expired. Request a new one." | — |
| PFA-AUTH-007 | 422 | info | Weak password | "Use at least 12 characters. Avoid common passwords." | zxcvbn ≥ 3 |
| PFA-USR-001 | 403 | warn | Role lacks permission | "You don't have access to this action. Ask your administrator." | audit denied attempt |
| PFA-USR-002 | 409 | info | Would remove last admin / default owner | "Assign another administrator (or default case owner) first." | — |
| PFA-USR-003 | 409 | info | Email already invited | "This person already has an account or a pending invite." | — |

### 4.2 Account & config (`ACC`, `SVY`)
| Code | HTTP | Level | Meaning | User message | Handling |
|---|---|---|---|---|---|
| PFA-ACC-001 | 422 | info | Invalid contact window | "Calling hours must be at least 2 hours long and end after they start." | — |
| PFA-ACC-002 | 422 | info | Cap out of range | "Enter a value between {min} and {max}." | — |
| PFA-ACC-003 | 409 | info | Cannot activate: missing prerequisites | "Before going live, set: {missing_list}." | list: default case owner, caller ID, active survey, audio ready |
| PFA-ACC-004 | 409 | info | Account paused | "Calling is paused for this account." | dial service skips |
| PFA-SVY-001 | 422 | info | Survey definition invalid | "The survey has errors: {errors}." | JSON schema errors listed |
| PFA-SVY-002 | 503 | error | Audio pre-render failed | "We couldn't prepare the voice prompts. We'll retry automatically." | retry job ×3, alert |
| PFA-SVY-003 | 409 | info | Missing language text | "Add the {language} version of question '{key}'." | — |

### 4.3 Ingestion (`ING`)
| Code | HTTP | Level | Meaning | User message |
|---|---|---|---|---|
| PFA-ING-001 | 422 | info | Not a CSV | "Please upload a .csv file." |
| PFA-ING-002 | 422 | info | Missing required columns | "The file is missing these columns: {columns}. Download the template to check." |
| PFA-ING-003 | 422 | warn | Too many invalid rows | "{pct}% of rows have errors, so the file wasn't processed. Fix the errors and upload again." |
| PFA-ING-004 | 422 | info | Encoding | "Save the file as CSV UTF-8 and upload again." |
| PFA-ING-005 | 413 | info | Too large | "Files can be up to 20 MB and 50,000 rows. Split the file and try again." |
| PFA-ING-006 | 409 | info | Duplicate file | "This file was already uploaded on {date}." |
| PFA-ING-007 | 404 | info | Batch not found (incl. cross-tenant, per doc 04 §1) | "That upload wasn't found." |
| PFA-ING-010 | row | — | Bad patient ID | "Row {n}: patient ID is missing or has invalid characters." |
| PFA-ING-011 | row | — | Bad phone | "Row {n}: phone number is not a valid Indian number." (never echo the number) |
| PFA-ING-012 | row | — | Bad date | "Row {n}: visit date must be a real past date ({format})." |
| PFA-ING-013 | row | — | Visit type | "Row {n}: visit type must be outpatient or diagnostic." |
| PFA-ING-014 | row-warn | — | Unknown department | "Row {n}: department '{dept}' is new and was added as unmapped." |
| PFA-ING-015 | row-warn | — | Unsupported language | "Row {n}: language '{lang}' isn't enabled; we'll detect it on the call." |
| PFA-ING-016 | row | — | Age | "Row {n}: age must be a whole number." |
| PFA-ING-017 | row | — | Consent flag | "Row {n}: consent flag must be yes/no." |
| PFA-ING-018 | row | — | Unknown location | "Row {n}: location '{loc}' isn't set up. Add it in Settings." |
| PFA-ING-020 | — | error | SFTP poll failed | (admin alert) "We couldn't read today's file from SFTP. Last success: {time}." |

### 4.4 Eligibility & suppression (`ELG`, `SUP`)
| Code | Meaning | UI label (suppression reason) |
|---|---|---|
| PFA-ELG-001 | minor | "Under 18" |
| PFA-ELG-002 | invalid_number | "Invalid number" |
| PFA-ELG-003 | opt_out | "Opted out" |
| PFA-ELG-004 | dnd | "On Do-Not-Disturb list" |
| PFA-ELG-005 | duplicate_encounter | "Duplicate visit (recent)" |
| PFA-ELG-006 | already_called_visit | "Already contacted for this visit" |
| PFA-ELG-007 | frequency_cap | "Contacted recently" |
| PFA-ELG-008 | stale_visit | "Visit too old" |
| PFA-ELG-009 | shared_number_review | "Shared number – needs review" |
| PFA-ELG-010 | out_of_scope_visit_type | "Visit type not in scope" |
| PFA-SUP-001 (409) | Phone already suppressed | "This number is already on the do-not-call list." |
| PFA-SUP-002 (403) | Cannot remove opt-out | "Patient opt-outs can't be removed. The patient must opt in again directly." |

### 4.5 Orchestration & telephony (`ORC`, `TEL`, `WH`)
| Code | Level | Meaning | Handling |
|---|---|---|---|
| PFA-ORC-001 | info | Outside contact window at dial time | skip, reschedule to next window start (never dial) |
| PFA-ORC-002 | info | Concurrency cap reached | leave queued; next tick |
| PFA-ORC-003 | warn | Suppressed at final pre-dial check | cancel call, log reason |
| PFA-ORC-004 | info | Retry cap reached | visit `exhausted` |
| PFA-ORC-005 | info | Daily cap reached | queue rolls to next day |
| PFA-ORC-006 | error | Leaked concurrency lease reconciled | reaper fixes; alert if > 5/h |
| PFA-ORC-007 | error | Adapter breaker open, dialing halted | alert P2 ops |
| PFA-TEL-001 | warn | place_call rejected by provider | retry per table; if auth → PFA-TEL-003 |
| PFA-TEL-002 | info | Busy/no-answer | retry policy |
| PFA-TEL-003 | critical | Provider auth/config error | halt dialing for platform, page on-call |
| PFA-TEL-004 | warn | Hangup failed | rely on timeout |
| PFA-TEL-005 | warn | Mid-call drop | mark partial, one retry |
| PFA-TEL-006 | info | Voicemail detected | hang up without message; one retry |
| PFA-TEL-007 | error | Transfer failed (safety path) | speak emergency number again, close; P1 case already created |
| PFA-WH-001 | warn | Invalid webhook signature | 401, security event |
| PFA-WH-002 | info | Duplicate webhook | ignore (idempotent) |

### 4.6 In-call (`CNS`, `CNV`, `STT`, `LLM`, `TTS`, `SAF`)
| Code | Meaning | Patient hears | System action |
|---|---|---|---|
| PFA-CNS-001 | Consent declined | `close_declined` | suppress visit, discard audio |
| PFA-CNS-002 | Consent ambiguous twice | `close_declined` | treat as declined |
| PFA-CNS-003 | Hang-up before consent | — | `abandoned_pre_consent`, discard audio |
| PFA-CNS-004 | Attempt to store survey data without consent (bug) | — | reject write, critical alert, fail test suite |
| PFA-CNS-005 | Recording withdrawn | `recording_withdrawn` | stop recording, `granted_unrecorded` |
| PFA-CNS-006 | Processing withdrawn | `close_stop` | purge call content |
| PFA-CNV-001 | Silence twice | `silence_final` | end, retry per policy if no data captured |
| PFA-CNV-002 | Repeated misunderstanding (≥ 2) | `offer_language` → `offer_human` | callback request case p3 |
| PFA-CNV-003 | Max duration reached | `close_time_limit` | `partial` if required fields missing |
| PFA-CNV-004 | Wrong person / wrong number | respective close | wrong number → invalidate phone for patient |
| PFA-STT-001 | Low confidence (< 0.55) | `confirm_low_conf` | if still low → skip field, flag review |
| PFA-STT-002 | Stream failure | `system_error` | end, `failed_system`, one retry |
| PFA-STT-003 | Unsupported language detected | `offer_language` | if none accepted → `offer_human` |
| PFA-LLM-001 | In-call timeout | (no audible error) fixed fallback | deterministic path continues |
| PFA-LLM-002 | Malformed JSON | fallback | re-ask once post-call |
| PFA-LLM-003 | Output failed guard (banned content) | fallback fixed probe | log sample for review |
| PFA-LLM-004 | Post-call extraction failed | — | `needs_human_review`, p3 case if negatives |
| PFA-TTS-001 | Primary voice failure | fallback voice | — |
| PFA-TTS-002 | All TTS failed | cached `system_error` | end call |
| PFA-SAF-001 | Emergency trigger | `safety_emergency` | P1 case sync, alert |
| PFA-SAF-002 | Safety concern (non-acute) | continue gently | P1 case post-call |
| PFA-SAF-003 | Clinical question | `clinical_boundary` | count; ≥ 2 → p2 follow-up case |
| PFA-SAF-004 | P1 case creation failed in-call | (patient already heard emergency script) | **critical**: write to fallback table + page on-call; retry every 30 s ×10 |

### 4.7 Cases (`CASE`)
| Code | HTTP | User message |
|---|---|---|
| PFA-CASE-001 | 409 | "This action isn't available while the case is {status}." |
| PFA-CASE-002 | 422 | "Choose someone to assign this case to." |
| PFA-CASE-003 | 422 | "That person can't be assigned cases for this department." |
| PFA-CASE-004 | 422 | "A resolution note (at least 20 characters) is required." |
| PFA-CASE-005 | 409 | "Cases can only be merged into an open case at the same location." |
| PFA-CASE-006 | 409 | "This case is already closed. Reopen it to make changes." |
| PFA-CASE-007 | 409 | "Invalidating a P1 case needs confirmation from a second quality user." |
| PFA-CASE-409 | 409 | "This case was updated by someone else. Reload to see the latest." |

### 4.8 Retention, deletion, system (`RET`, `DEL`, `SYS`, `API`)
| Code | HTTP | Meaning | User message |
|---|---|---|---|
| PFA-RET-001 | 410 | Audio/transcript purged | "This recording was deleted under your retention policy on {date}." |
| PFA-RET-002 | — | Purge job failure | admin alert "Scheduled data deletion failed; retrying." |
| PFA-DEL-001 | 409 | Requester tried to approve own request | "A different administrator must approve this deletion." |
| PFA-DEL-002 | 404 | Patient not found | "No patient matches those details." |
| PFA-DEL-003 | — | Deletion job partial failure | admin alert; status `failed`, auto-retry |
| PFA-SYS-001 | 500 | Unexpected | "Something went wrong on our side. Please try again. (Ref: {request_id})" |
| PFA-SYS-002 | 503 | DB unavailable/contention | "We're having trouble saving right now. Please try again in a minute." |
| PFA-SYS-003 | 503 | Maintenance | "We're doing scheduled maintenance until {time}." |
| PFA-SYS-011 | 404 | Demo route hit while `DEMO_MODE` is off (Demo MVP) | "Not found." |
| PFA-DEMO-001 | 500 | Adapter called with an unknown prompt_id / missing variables (Demo MVP, internal bug not a vendor failure) | "Something went wrong on our side. Please try again." |
| PFA-DEMO-002 | 401 | Provider rejected the API key on save-and-test or a live call (Demo MVP) | "That API key was rejected. Check it and try again." |
| PFA-DEMO-003 | 502 | Provider request failed for another reason (Demo MVP) | "Couldn't reach the AI provider. Please try again." |
| PFA-DEMO-004 | 502 | Provider returned output that didn't match the expected structure, after one retry (Demo MVP) | "The AI gave an unexpected response. Please try again." |
| PFA-DEMO-005 | 504 | Provider request timed out (Demo MVP) | "The AI took too long to respond. Please try again." |
| PFA-DEMO-006 | 404 | Demo call ID doesn't exist (Demo MVP) | "That call couldn't be found." |
| PFA-DEMO-007 | 422 | Turn submitted or end requested on a demo call that already ended (Demo MVP) | "This call has already ended." |
| PFA-DEMO-008 | 422 | Turn submitted for a provider with no connected (saved-and-tested) API key (Demo MVP) | "{provider} isn't configured yet. Save and test a working API key for it in Settings, then try again." |
| PFA-DEMO-009 | 429 | Provider rate limit hit — e.g. a free-tier model's daily request cap (Demo MVP) | "This model is rate-limited right now. Try a different model, or wait and retry." |
| PFA-DEMO-010 | 422 | Demo call start attempted for a patient on the do-not-call list (PRD v2) | "This patient has opted out of future calls." |
| PFA-DEMO-011 | 404 | Escalation ID doesn't exist (PRD v2) | "That escalation couldn't be found." |
| PFA-DEMO-012 | 404 | Visit ID doesn't exist, starting a call from an ingested visit (PRD v2 Phase 8) | "That visit couldn't be found." |
| PFA-DEMO-013 | 422 | Starting a call from a visit that already has 3 call attempts (PRD v2 Phase 8) | "This visit has already had the maximum of 3 call attempts." |
| PFA-API-001 | 422 | Request validation | "Some fields need attention." (+ field errors) |
| PFA-API-002 | 429 | Rate limited | "You're going a bit fast. Please wait {seconds} seconds." |
| PFA-API-003 | 409 | Idempotency key reused with different body | "This request conflicts with an earlier one. Refresh and try again." |

## 5. In-call fallback matrix (implement all)

| Failure | Recovery sequence |
|---|---|
| STT confidence < threshold | `confirm_low_conf` once → still low → skip field, `needs_human_review` |
| Silence | reprompt once → `silence_final` / offer keypad (DTMF 1–5 for score questions) → callback |
| Repeated misunderstanding (≥ 2) | `offer_language` → `offer_human` (callback case) |
| LLM timeout | Use deterministic next-question; skip probe; if 2 LLM timeouts in a call, disable LLM for rest of call |
| LLM malformed output | Re-ask once (post-call only); in-call → fallback |
| TTS failure | fallback voice → fallback provider → cached generic → end |
| Telephony drop | exactly one retry, resume at first unanswered field (after re-consent short form) |
| Medical question | `clinical_boundary` + human route |
| Distress/safety phrase | `safety_emergency` immediately, stop survey |
| Agent process crash | LiveKit disconnect → call `failed_system`; post-call extraction on persisted state; one retry if no consent captured yet |

Resume-after-drop short consent: EN "Hello again from {hospital}. We got cut off. This call may be
recorded. Shall we continue where we left off?" / HI "{hospital} से फिर से नमस्ते। कॉल कट गई थी। यह कॉल
रिकॉर्ड की जा सकती है। क्या हम वहीं से आगे बढ़ें?"

## 6. Dashboard message conventions

- Tone: plain, calm, specific, action-oriented. Say what happened + what to do. No blame, no jargon.
- Toast success examples: "Case acknowledged." · "Assigned to R. Iyer." · "File received. We'll email
  you when processing finishes." · "Settings saved. Changes apply to calls from now on."
- Confirmations: "Pause all calling for {account}? Calls in progress will finish; no new calls will start."
- Never show: vendor names, SQL/stack traces, raw phone numbers, other tenants' data.

## 7. Logging format for errors

```json
{"ts":"…","level":"error","event":"adapter.failure","code":"PFA-TTS-001",
 "account_id":"acc_…","call_id":"call_…","adapter":"tts","provider":"cartesia",
 "latency_ms":1203,"attempt":1,"retryable":true,"request_id":"req_…"}
```
Redaction processor removes/masks: `phone*`, `text`, `verbatim*`, `transcript*`, `utterance`, emails
(masked `r***@hospital.in`), auth headers, tokens.
