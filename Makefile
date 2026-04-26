.PHONY: help up down down-v logs logs-api logs-worker install lint fmt typecheck \
        test test-unit test-load migrate migrate-new seed clean

help:
	@echo "Targets:"
	@echo "  up              Build + start all services (detached)"
	@echo "  down            Stop services (keep volumes)"
	@echo "  down-v          Stop services and remove volumes (full reset)"
	@echo "  logs            Tail all service logs"
	@echo "  logs-api        Tail api logs only"
	@echo "  logs-worker     Tail worker logs only"
	@echo "  install         uv sync (runtime + dev deps)"
	@echo "  lint            ruff check + ruff format --check"
	@echo "  fmt             ruff format + ruff check --fix"
	@echo "  typecheck       mypy src/ (strict)"
	@echo "  test            Spin test services -> pytest -> teardown"
	@echo "  test-unit       Unit tests only (no services)"
	@echo "  test-load       Locust against localhost:8000"
	@echo "  migrate         alembic upgrade head (inside api container)"
	@echo "  migrate-new     Generate a new migration (MSG=\"description\")"
	@echo "  seed            Load infra/scripts/seed.sql into postgres"
	@echo "  clean           Remove caches and build artifacts"

up:
	docker compose up --build -d

down:
	docker compose down

down-v:
	docker compose down -v

logs:
	docker compose logs -f --tail=200

logs-api:
	docker compose logs -f --tail=200 api

logs-worker:
	docker compose logs -f --tail=200 worker

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:
	uv run mypy src/

test:
	docker compose -f tests/docker-compose.test.yml up -d
	uv run pytest --cov=src/rate_limiter --cov-report=term-missing
	docker compose -f tests/docker-compose.test.yml down -v

test-unit:
	uv run pytest tests/unit -xvs

test-load:
	uv run locust -f tests/load/locustfile.py --host http://localhost:8000

migrate:
	docker compose exec api alembic upgrade head

migrate-new:
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

seed:
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-rate_limiter} < infra/scripts/seed.sql

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
