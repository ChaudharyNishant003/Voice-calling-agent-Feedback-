# 0001 — Stack choice

Status: Accepted

## Context
PFA needs a backend that can hold strict async I/O, strong typing, and a mature async ORM; a voice
runtime with first-class barge-in/streaming support; and a dashboard stack the team can move fast
in. See CLAUDE.md §3 for the full pinned table.

## Decision
Python 3.12 + FastAPI + Pydantic v2 for the API; SQLAlchemy 2.x async + Alembic for persistence on
Postgres 16 (pgcrypto for column-level crypto helpers); Redis 7 as broker/cache; Celery 5 + Beat for
background jobs and schedules; LiveKit Agents (Python SDK) as the voice runtime, with Plivo for
Indian PSTN telephony, Deepgram Nova-3 for STT, Gemini Flash for LLM, Cartesia Sonic for TTS — each
behind an adapter (ADR 0002); S3-compatible storage (SSE-KMS, India region) for audio; Next.js 14
App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query for the dashboard.

## Consequences
- Async end-to-end (FastAPI, SQLAlchemy, Celery-adjacent) keeps the API responsive under the
  per-turn latency budget (doc 01 §8) without a separate async runtime split.
- LiveKit Agents gives streaming STT/TTS, barge-in, and SIP bridging out of the box, which a
  hand-rolled PSTN media pipeline would otherwise cost sprints to build.
- Every vendor choice (Plivo/Deepgram/Gemini/Cartesia) sits behind the adapter pattern (ADR 0002)
  specifically so a wrong vendor bet is a swap, not a rewrite.
- Any change to this table requires a new ADR (CLAUDE.md §3) — it is not a "just this once" edit.
