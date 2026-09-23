"""Task modules must be imported here so `celery_app.autodiscover_tasks(["app.workers"])`
(which imports this package, not each submodule individually) actually registers them.
"""

from app.workers.tasks import audit as audit  # noqa: F401
