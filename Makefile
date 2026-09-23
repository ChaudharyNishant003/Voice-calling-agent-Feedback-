.PHONY: up down migrate seed test test-safety test-e2e lint bench load

COMPOSE = docker compose -f infra/docker-compose.yml

up:
	$(COMPOSE) up --build -d
	@echo "dashboard: http://localhost:3000   api: http://localhost:8010/api/v1/health/ready   mailpit: http://localhost:8025"

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) exec api alembic upgrade head

seed:
	$(COMPOSE) exec api python -m app.db.seed

# tests/integration needs a Docker socket (testcontainers spins up real Postgres) — mounted
# ad hoc here since the api service itself doesn't need one. On Docker Desktop for Windows/Mac this
# needs TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal (and RYUK disabled, since the reaper
# sidecar hits the same networking quirk) — see docs/11_BUILD_PLAN.md's S1.1 note. Neither is
# needed on native Linux CI runners (doc 10 §4), so they're harmless no-ops there.
test:
	$(COMPOSE) run --rm api pytest tests/unit
	$(COMPOSE) run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
		-e TESTCONTAINERS_RYUK_DISABLED=true \
		api pytest tests/integration

# safety/, e2e/ only hold README stubs until their sprints add real tests (docs/11_BUILD_PLAN.md) —
# run conditionally so an empty suite isn't a false failure.

test-safety:
	$(COMPOSE) run --rm api sh -c 'ls tests/safety/test_*.py >/dev/null 2>&1 && pytest tests/safety || echo "no safety tests yet (Sprint 3-4)"'

test-e2e:
	$(COMPOSE) run --rm api sh -c 'ls tests/e2e/test_*.py >/dev/null 2>&1 && pytest tests/e2e || echo "no e2e tests yet (Sprint 3+)"'

lint:
	$(COMPOSE) run --rm api ruff check app tests
	$(COMPOSE) run --rm api mypy app
	$(COMPOSE) run --rm api lint-imports
	cd dashboard && npm run lint && npm run typecheck

bench:
	$(COMPOSE) run --rm api python -m eval.latency.run

load:
	k6 run eval/load/k6_script.js
