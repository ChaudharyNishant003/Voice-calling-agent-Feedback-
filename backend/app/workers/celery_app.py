"""Celery app factory. Queues: ingest, dial, postcall, notify, maintenance
(docs/01_ARCHITECTURE.md §2). Task modules and the beat schedule land alongside their owning
services starting Sprint 1 (docs/11_BUILD_PLAN.md).
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.core.config import get_settings

QUEUES = ("ingest", "dial", "postcall", "notify", "maintenance")


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("pfa", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.task_default_queue = "maintenance"
    app.conf.task_queues = tuple(Queue(name) for name in QUEUES)
    app.autodiscover_tasks(["app.workers.tasks"])
    return app


celery_app = create_celery_app()
