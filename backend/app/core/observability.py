"""Observability base (docs/09_OBSERVABILITY_AND_COST.md §1) — built in Sprint 0, not bolted on.

Wires: Prometheus `/metrics`, OpenTelemetry instrumentation (FastAPI/SQLAlchemy/Celery/httpx),
and Sentry with PII scrubbing. The `call_events` table itself is a Sprint 1 migration (S1.1); this
module only provides the writer *seam* (`app.services.metrics_service.emit_call_event`) that
Sprint 1+ code calls into — see that module's docstring for why it's a stub today.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, make_asgi_app

from app.core.config import Settings
from app.core.logging import redaction_processor

if TYPE_CHECKING:
    from fastapi import FastAPI

METRICS_REGISTRY = CollectorRegistry()


def configure_tracing(*, service_name: str) -> TracerProvider:
    """OTel SDK setup (docs/09 §1). Exporter is OTLP when configured; a no-op provider otherwise so
    tracing calls are always safe to make, even before the optional otel-collector profile is up.
    """
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    trace.set_tracer_provider(provider)
    return provider


def add_otlp_exporter(provider: TracerProvider, *, endpoint: str) -> None:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))


def configure_sentry(settings: Settings, *, service_name: str) -> None:
    """PII scrubbing on (doc 09 §1: send_default_pii=False). No-op if SENTRY_DSN is unset."""
    if not settings.sentry_dsn:
        return

    import sentry_sdk
    from sentry_sdk.types import Event, Hint

    def _before_send(event: Event, hint: Hint) -> Event | None:
        # Route every outgoing event through the same redaction rule logging uses, so a stray
        # phone number / transcript in an exception message can't leak to Sentry either.
        return redaction_processor(None, "sentry", dict(event))  # type: ignore[return-value]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        send_default_pii=False,
        before_send=_before_send,
        server_name=service_name,
    )


def mount_metrics(app: FastAPI) -> None:
    """Expose `/metrics` for Prometheus scraping (doc 09 §1)."""
    app.mount("/metrics", make_asgi_app(registry=METRICS_REGISTRY))


def instrument_fastapi(app: FastAPI) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
