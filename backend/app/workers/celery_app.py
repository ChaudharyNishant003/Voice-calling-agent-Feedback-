"""Celery app factory. Queues: ingest, dial, postcall, notify, maintenance
(docs/01_ARCHITECTURE.md §2). Task modules and the beat schedule land alongside their owning
services starting Sprint 1 (docs/11_BUILD_PLAN.md).
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.core.config import get_settings
from app.workers.beat_schedule import BEAT_SCHEDULE

QUEUES = ("ingest", "dial", "postcall", "notify", "maintenance")


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("pfa", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.task_default_queue = "maintenance"
    app.conf.task_queues = tuple(Queue(name) for name in QUEUES)
    app.conf.beat_schedule = BEAT_SCHEDULE
    return app


celery_app = create_celery_app()

# `autodiscover_tasks()` only actually imports its target package via a signal fired during
# Celery's own worker bootstrap (app.loader.import_default_modules()) — it doesn't reliably
# register anything outside a real `celery worker` process (confirmed empirically: a plain script
# importing celery_app and calling .finalize() left the task registry empty even with
# autodiscover_tasks(["app.workers"], force=True) present). A direct import here is simple and
# unconditionally correct instead — app.workers.tasks's __init__.py pulls in every task submodule
# (e.g. app.workers.tasks.audit), which is what actually runs each @celery_app.task-decorated
# function's registration. This has to come *after* `celery_app` is assigned above, since task
# modules import `celery_app` from this module to get the `@celery_app.task` decorator — importing
# tasks any earlier (e.g. inside create_celery_app()) would be a circular import.
import app.workers.tasks  # noqa: E402, F401
