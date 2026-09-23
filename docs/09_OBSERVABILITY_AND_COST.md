# 09 — Observability & Cost Telemetry

"We cannot price what we cannot measure." Instrumentation is built in Sprint 0, not bolted on.

## 1. Stack

| Concern | Tool (swappable) |
|---|---|
| Logs | structlog JSON → stdout → collector (Loki / cloud logging) |
| Metrics | Prometheus client (`/metrics` on api, worker, agent) → Prometheus/Grafana |
| Traces | OpenTelemetry SDK (FastAPI, SQLAlchemy, Celery, httpx instrumentation) → OTLP |
| Errors | Sentry (PII scrubbing on, `send_default_pii=False`) |
| Call replay | `call_events` table + replay tool (`scripts/replay_call.py`, dashboard Call → Events tab) |

Trace context propagates: API request → Celery task → agent job via `traceparent` in job metadata, and
`call_id` is a span attribute everywhere.

## 2. Structured call events (`call_events`)

Every event: `{call_id, ts, type, data}`. Required types:

| type | data |
|---|---|
| `call.queued` / `call.dial_attempt` / `call.status` | attempt_no, provider status, reason |
| `state.transition` | from, to, trigger (utterance_id / timer / interrupt), turn_index |
| `consent.change` | from, to, method (lexicon match id) |
| `turn.patient` | turn_index, language, stt_confidence, duration_ms (no text) |
| `turn.agent` | turn_index, utterance_key or `llm:<prompt_id>`, cached(bool) |
| `latency.turn` | endpointing_ms, stt_ms, decision_ms, llm_ms, tts_first_byte_ms, total_ms |
| `adapter.call` | adapter, provider, op, latency_ms, ok, error_code, units (sec/tokens/chars) |
| `interrupt` | kind (safety/opt_out/stop/clinical/busy/lang/confusion), detector (rule id / llm) |
| `safety.trigger` | group, rule_id, llm_hint, action |
| `bargein` | tts_stopped_after_ms |
| `extraction.result` | fields_count, complaints_count, method, prompt_version |
| `case.created` | case_id, priority |
| `cost.final` | breakdown paise |

Text content is never in events; replay shows text only via the audited transcript endpoint.

## 3. Metrics (Prometheus names)

**Reach**
- `pfa_visits_ingested_total{account}` · `pfa_visits_eligible_total` · `pfa_suppressed_total{reason}`
- `pfa_call_attempts_total{account,outcome}` · `pfa_answer_rate` (recording rule)

**Conversation**
- `pfa_calls_completed_total{account,language}` · `pfa_call_duration_seconds` (histogram)
- `pfa_turn_latency_seconds{segment}` (histogram: endpointing, stt, llm, tts_first_byte, total)
- `pfa_bargein_stop_seconds` · `pfa_language_switch_total` · `pfa_llm_fallback_total{reason}`
- `pfa_deterministic_turn_ratio` (target 0.7–0.9)

**Data quality / insight**
- `pfa_required_field_completion_ratio` · `pfa_low_confidence_turns_total`
- `pfa_extraction_failures_total` · `pfa_human_review_queue_size`

**Safety**
- `pfa_safety_triggers_total{group,detector}` · `pfa_safety_case_creation_seconds`
- `pfa_safety_review_outcome_total{result=confirmed|false_positive|missed}` (from human review)

**Operations**
- `pfa_cases_open{priority}` · `pfa_case_ack_seconds` · `pfa_case_close_seconds` ·
  `pfa_sla_breaches_total{priority,type}` · `pfa_case_reopen_total`

**Platform**
- `pfa_concurrent_calls{account}` · `pfa_errors_total{code}` · `pfa_adapter_latency_seconds{adapter,op}`
  · `pfa_adapter_errors_total{adapter,code}` · `pfa_breaker_state{adapter}` · Celery queue depth/age

**Cost**
- `pfa_call_cost_paise{component}` (histogram) · `pfa_cost_per_completed_call_paise` (recording rule)

North-star (computed daily, stored in `daily_metrics`): **actionable insights per eligible patient** =
(complaints with verbatim + dimension scores with confidence ≥ 0.7) / eligible visits.

## 4. Alerts

| Alert | Condition | Severity | Route |
|---|---|---|---|
| Safety case creation failure | any `PFA-SAF-004` | critical | page on-call immediately |
| Out-of-window dial | nightly compliance query > 0, or real-time guard triggered | critical | page |
| Call to suppressed number | compliance query > 0 | critical | page + pause account |
| Survey before consent | compliance query > 0 | critical | page + pause platform dialing |
| Completion rate drop | < 60% of answered over 1 h (min 20 calls) | high | ops channel |
| Turn latency P90 | > 3.5 s for 15 min | high | ops |
| Adapter error spike | error rate > 5% over 5 min or breaker open | high | ops |
| P1 ack SLA breached | any | high | account quality lead (product) + ops visibility |
| Queue backlog | `dial` queue age > 2 min / `postcall` > 15 min | medium | ops |
| Cost anomaly | cost per completed call > ₹24 or > 2× 7-day median for 1 h | medium | ops + product |
| Retention job failure | job failed | medium | ops |
| Audit chain break | nightly verify fails | critical | security |
| SFTP missing file | no file by 11:00 local on a contact day | low | account admin email + ops |

Every alert has a runbook link (doc 10 §6).

## 5. Cost telemetry

### 5.1 Per-call breakdown (stored in `calls.cost_breakdown`, paise)
```json
{
  "telephony": 180, "stt": 95, "llm": 40, "tts": 120, "infra": 60, "support_alloc": 0,
  "units": {"telephony_billed_sec": 312, "stt_sec": 290, "llm_in_tokens": 4200,
            "llm_out_tokens": 380, "tts_chars": 1650, "tts_cached_chars": 900},
  "rates_version": "2026-10-01"
}
```
- Telephony from Plivo `billed_duration` × rate (per-minute rounding as provider bills).
- STT from streamed seconds; LLM from token counts per call; TTS from **non-cached** characters.
- Infra allocation: monthly infra cost ÷ completed minutes, recalculated nightly (`cost_rates` row).
- Support allocation: set at 0 in telemetry; added in monthly finance report.
- Attempts that don't connect still record telephony cost (for margin), but **billing to customers
  counts completed calls/minutes only**.

### 5.2 Cost dashboard (admin)
Cost per completed call (P50/P90), by component, by language, trend; share of deterministic turns;
cached TTS ratio; retries' cost share.

### 5.3 Optimisation levers implemented in MVP
1. Pre-rendered cached audio for greeting, consent, boundaries, closings, and all fixed questions per
   language (cache key = hash(text, voice, rate)).
2. Deterministic interpretation for scores and common answers; LLM only on ambiguity/probe.
3. Small model in-call; post-call extraction async (can use larger model only on retry/difficult flag).
4. Early abandonment short-circuit: no post-call LLM for abandoned/declined calls.
5. Retry cap + callback scheduling.
6. Tiered audio retention.
7. Daily batch analytics (materialised views refreshed every 15 min, not per request).
