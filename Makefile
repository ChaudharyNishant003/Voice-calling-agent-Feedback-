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

# integration/, safety/, e2e/ only hold README stubs until their sprints add real tests
# (docs/11_BUILD_PLAN.md) — run conditionally so an empty suite isn't a false failure.
test:
	$(COMPOSE) run --rm api pytest tests/unit
	$(COMPOSE) run --rm api sh -c 'ls tests/integration/test_*.py >/dev/null 2>&1 && pytest tests/integration || echo "no integration tests yet (Sprint 1+)"'

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
