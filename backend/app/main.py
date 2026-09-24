"""FastAPI app factory (docs/01_ARCHITECTURE.md §3). Sprint 0 wires cross-cutting concerns only —
routers beyond `/health` are added as their sprints land (docs/11_BUILD_PLAN.md).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.me import router as me_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.observability import (
    configure_sentry,
    configure_tracing,
    instrument_fastapi,
    mount_metrics,
)

SERVICE_NAME = "pfa-api"


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_startup()

    configure_logging(json=settings.app_env != "local")
    configure_tracing(service_name=SERVICE_NAME)
    configure_sentry(settings, service_name=SERVICE_NAME)

    app = FastAPI(title="Patient Feedback Voice Agent API", version="0.1.0")

    @app.middleware("http")
    async def _assign_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    install_error_handlers(app)
    mount_metrics(app)
    instrument_fastapi(app)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")
    app.include_router(ingestion_router, prefix="/api/v1")

    return app


app = create_app()
