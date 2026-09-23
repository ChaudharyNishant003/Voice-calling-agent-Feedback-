FROM python:3.12-slim AS base

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN pip install --no-cache-dir -e ".[dev]"

CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]
