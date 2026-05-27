.PHONY: dev test lint format migrate revision logs shell down clean

COMPOSE     := docker compose
COMPOSE_DEV := $(COMPOSE) -f docker-compose.yml
BOT_SVC     := bot

dev:
	$(COMPOSE_DEV) up --build

down:
	$(COMPOSE_DEV) down

test:
	uv run pytest --cov=bot --cov-report=term-missing --cov-fail-under=80

lint:
	uv run black --check bot tests
	uv run isort --check-only bot tests
	uv run mypy bot

format:
	uv run black bot tests
	uv run isort bot tests

migrate:
	$(COMPOSE_DEV) exec $(BOT_SVC) uv run alembic upgrade head

revision:
	@if [ -z "$(m)" ]; then echo "usage: make revision m=\"message\""; exit 1; fi
	$(COMPOSE_DEV) exec $(BOT_SVC) uv run alembic revision --autogenerate -m "$(m)"

logs:
	$(COMPOSE_DEV) logs -f $(BOT_SVC)

shell:
	$(COMPOSE_DEV) exec $(BOT_SVC) /bin/bash

clean:
	rm -rf .mypy_cache .pytest_cache .coverage htmlcov coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
