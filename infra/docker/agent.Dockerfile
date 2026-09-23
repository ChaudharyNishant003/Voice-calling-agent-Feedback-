FROM python:3.12-slim AS base

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN pip install --no-cache-dir -e ".[dev]"

# Real LiveKit Agents entrypoint lands in Sprint 3 (docs/11_BUILD_PLAN.md S3.1); this stub keeps
# the container up so `docker compose up` brings up the full service list from doc 10 §2.
CMD ["python", "-m", "app.agent.entrypoint"]
