"""Task modules must be imported here — `celery_app.py` imports this package (not each submodule
individually) after `celery_app` is assigned, which is what actually registers every
`@celery_app.task`-decorated function; see that module's docstring for why plain
`autodiscover_tasks()` doesn't work outside a real `celery worker` process.
"""

from app.workers.tasks import audit as audit  # noqa: F401
from app.workers.tasks import ingestion as ingestion  # noqa: F401
