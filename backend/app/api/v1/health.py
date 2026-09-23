"""Liveness/readiness endpoints. `/health/ready` is the Sprint 0 exit signal
(docs/11_BUILD_PLAN.md S0.1 — 'make up starts all services; /health/ready green').
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    # Sprint 1 extends this to check DB/Redis connectivity once those integrations exist.
    return {"status": "ok"}
