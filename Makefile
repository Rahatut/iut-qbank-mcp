.PHONY: install install-dev test test-unit test-integration test-e2e lint fmt typecheck clean up down migrate migrate-down

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pre-commit install

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

test-unit:
	pytest tests/unit -m unit -v

test-integration:
	pytest tests/integration -m integration -v

test-e2e:
	pytest tests/e2e -m e2e -v

test-cov:
	pytest tests/unit -m unit --cov=src --cov-report=html --cov-report=term-missing

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	ruff check .

fmt:
	ruff format .

typecheck:
	mypy src/

check: lint typecheck

# ── Services ──────────────────────────────────────────────────────────────────
up:
	docker compose up -d postgres qdrant minio

down:
	docker compose down

up-all:
	docker compose up -d

logs:
	docker compose logs -f

# ── Database ──────────────────────────────────────────────────────────────────
migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migrate-history:
	alembic history --verbose

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml
