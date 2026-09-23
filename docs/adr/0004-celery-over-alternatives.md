# 0004 — Celery + Beat over alternatives for background jobs

Status: Accepted

## Context
PFA needs several distinct background workloads with different latency/priority profiles:
low-latency dial ticks (doc 01 §2, every 30s), ingestion processing (up to 50k rows), post-call
extraction, SLA ticks, notification batching/digests, and retention/deletion jobs — plus scheduled
triggers (SFTP poll, dial ticks, SLA ticks, digests) via Celery Beat. Alternatives considered:
RQ (simpler, but weaker scheduling/queue-routing story), a cloud-managed queue (adds a hosting
dependency ahead of the India-residency decision, Open Question #9), and a bespoke asyncio-based
scheduler (more code to own for less proven reliability).

## Decision
Celery 5 + Celery Beat, backed by Redis 7 (already required as the app's cache/rate-limit/
concurrency-semaphore store — doc 01 §2), with named queues `ingest`, `dial`, `postcall`, `notify`,
`maintenance` (doc 01 §2) so the low-latency `dial` queue can be staffed and scaled independently
of bulk `ingest`/`postcall` work.

## Consequences
- One broker (Redis) serves the queue, the concurrency semaphore (doc 01 §6), rate limits, and the
  prompt-audio cache index — fewer moving pieces to run locally (`make up`) and in production.
- Celery's mature retry/backoff primitives map directly onto the bounded-retry rule (CLAUDE.md §5 —
  "never add unlimited retries") and the per-operation retry table in doc 06 §3.
- Beat runs as a single leader instance (Redis leader lock, doc 10 §5); this is an accepted
  single point of scheduling failure for MVP, mitigated by the "queue backlog" and "SFTP missing
  file" alerts (doc 09 §4) rather than by running Beat HA from day one.
- Sprint 0 ships the Celery app factory and named queues only (`app/workers/celery_app.py`); actual
  tasks and the beat schedule are added per-service starting Sprint 1.
