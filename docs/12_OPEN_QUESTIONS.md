# 12 — Open Questions & Assumptions Register

Claude Code: **do not resolve these alone.** Use the stated default, keep it configurable, and flag it
in the PR. Add new questions at the bottom with the next number.

| # | Question | Owner | Blocking? | Default used until answered |
|---|---|---|---|---|
| 1 | Plivo India entity registration, DLT, number provisioning, recording arrangements confirmed? | Business | Blocks production | Staging only, allowlisted numbers |
| 2 | Which DPDP Rules 2025 obligations are live at launch date? | Legal | Blocks production | Build all controls in doc 07 §7 |
| 3 | Is the post-visit feedback call "service/transactional" or "promotional" under current TCCCPR? | Telecom counsel | Yes | `DND_STRICT=true` (suppress DND for all) |
| 4 | Default audio retention per account? | Business + hospital | Yes for purge config | 30 days audio, 180 transcripts, 365 verbatims |
| 5 | Which regional language for pilot #1? | Sales / pilot account | Yes for STT routing | EN + HI only; regional slot empty |
| 6 | NPS or CSAT as default primary metric? | Product + pilot | No | CSAT 1–5, configurable |
| 7 | Deepgram real-world accuracy on 8 kHz Indian PSTN audio? | Engineering (benchmark) | Yes for language expansion | Measure in Sprint 8 |
| 8 | Does the pilot account have a named escalation owner? | Sales | Blocks pilot | Activation blocked without it |
| 9 | India-region hosting / residency required by pilot IT? | Sales / IT review | Affects deployment | India region for all stateful services |
| 10 | Complaint taxonomy universal or per-account? | Product | No | Default taxonomy, per-account override |
| 11 | When patient withdraws *recording* but continues, may we keep the transcript text? | Legal + product | Yes for S3.7 | Keep structured answers + verbatims only; no full transcript, no audio |
| 12 | Who reviews Hindi/regional scripts (native speaker + hospital sign-off)? | Product + pilot | Blocks production | English/Hindi drafts in doc 03 |
| 13 | Allow proxy feedback (family member speaking for patient)? | Pilot account + legal | No | `allow_proxy_feedback=false` |
| 14 | Emergency number to speak: 112 only, or also hospital urgent line; warm transfer allowed? | Pilot account + clinical advisor | Yes for S3.6 | Speak 112 + hospital line if configured; warm transfer off |
| 15 | Clinical advisor to sign off safety lexicon and golden set? | Business | Blocks production | Team-built list, flagged unreviewed |
| 16 | LiveKit Cloud vs self-hosted for pilot? | Engineering + pilot IT | Affects deploy | LiveKit Cloud in staging |
| 17 | Breach notification window committed in DPA? | Legal | No for build | Runbook assumes ≤ 24 h to fiduciary |
| 18 | Should the agent say the doctor's name in questions (privacy vs clarity)? | Product + pilot | No | Only after identity confirmed; config flag, default off |
| 19 | Keypad (DTMF) fallback for score questions — enabled at launch? | Product | No | Enabled for score questions after 2 misunderstandings |
| 20 | Human callback staffing: who calls patients who asked for a human? | Pilot account | Yes for pilot | Creates P3 case to default owner |
| 21 | Doc 07 §3 says phone/transcript encryption uses a "per-account DEK wrapped by KMS KEK," implying a stored wrapped DEK, but doc 02's DDL has no table for it. Confirm the schema addition. | Engineering | No for build | Add `account_encryption_keys(account_id, wrapped_dek, kek_id, created_at, rotated_at)` in migration 0008; built in S1.1/S1.2 |
| 22 | `suppression_reason` enum (doc 02 §1) has `consent_declined_visit` and `missing_required_field`, but doc 03 §1's 11-rule eligibility table doesn't assign either a rule. Are these meant to be set elsewhere (e.g. ingestion-time), or is the rule table missing a step? | Product | Yes for S1.7 | `domain/eligibility.py` implements exactly the 11 documented rules; these two enum values stay unused until answered |
| 23 | Doc 04 §1 / doc 07 §2 describe refresh tokens as "opaque, hashed in DB, with rotation and reuse detection," but doc 02's DDL has no table for it. Confirm the schema addition. | Engineering | No for build | Add `refresh_tokens(token_id, user_id, family_id, token_hash, created_at, expires_at, revoked_at, replaced_by)` in migration 0012; built in S1.3 |
| 24 | Doc 04 §4 describes two per-account ingestion settings — the `PFA-ING-003` invalid-row threshold ("configurable", default 30%) and the visit-date format ("`YYYY-MM-DD` or `DD-MM-YYYY` (account setting)") — but doc 02's DDL has no columns for either. Confirm the schema addition. | Engineering | No for build | Add `accounts.ingest_error_threshold_pct` (default 30) and `accounts.ingest_date_format` (default `YYYY-MM-DD`) in migration 0013; built in S1.6 |
| 25 | The ingestion worker needs the raw uploaded CSV bytes, but `adapters/storage/s3.py` (`ObjectStorageAdapter`) is a deliberate stub deferred to Sprint 3 (audio), and doc 02 has no other column for it. Confirm whether Sprint 1 should store the raw file in Postgres as a stopgap (this default), pass it through the Celery broker instead, or pull the S3 adapter forward. No retention/purge job exists for this data yet either — Sprint 1 doesn't include retention work. | Engineering | No for build | Add `ingestion_batches.content bytea` (nullable) in migration 0014; built in S1.6. Revisit when the S3 adapter and retention job land |

## Evidence quality reminder
Market sizes, pricing, cost bands and vendor latency/language claims are planning ranges or vendor
claims, not verified for Indian PSTN. Do not harden them into product promises or contract terms before
the validation work in doc 08 §8 and the pilot.
