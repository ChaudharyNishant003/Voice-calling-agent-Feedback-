# Production image for the API service (Railway). Separate from api.Dockerfile, which is
# dev-only (--reload, bind-mounted source, dev extras) — this installs without the dev extras and
# runs uvicorn without --reload, and reads $PORT (Railway assigns it dynamically) rather than a
# fixed 8000.
FROM python:3.12-slim AS base

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app

RUN pip install --no-cache-dir -e "."

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
