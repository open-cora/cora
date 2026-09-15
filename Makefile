.PHONY: install dev db-up db-down db-reset lint typecheck test test-unit test-int \
        test-contract test-noio test-db test-coverage store-durations diff-coverage \
        fmt clean help migrate-status migrate-apply migrate-new migrate-hash \
        precommit precommit-run arch-check arch-show openapi-snapshot

API_DIR := apps/api
COMPOSE := docker compose -f infra/docker-compose.yml
ATLAS_DIR := infra/atlas
LOCAL_DB_URL ?= postgres://aroc:aroc@localhost:5433/aroc?sslmode=disable

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv (in apps/api)"
	@echo "  dev             Run FastAPI dev server (reload, :8000)"
	@echo "  db-up           Start Postgres + pgvector via Docker Compose"
	@echo "  db-down         Stop Postgres"
	@echo "  db-reset        Stop Postgres and wipe its volume"
	@echo "  migrate-status  Show pending migrations against local DB"
	@echo "  migrate-apply   Apply pending migrations to local DB"
	@echo "  migrate-new     Generate a new migration skeleton (name=<short_name>)"
	@echo "  migrate-hash    Recompute atlas.sum after editing migrations by hand"
	@echo "  lint            Run ruff check + format check"
	@echo "  fmt             Run ruff format and auto-fix"
	@echo "  typecheck       Run pyright (strict)"
	@echo "  test            Run all tests"
	@echo "  test-unit       Run only unit tests"
	@echo "  test-int        Run only integration tests"
	@echo "  test-contract   Run only contract tests"
	@echo "  test-noio       Run the no-DB CI lane (unit + architecture + contract)"
	@echo "  test-db         Run the DB CI lane (integration + e2e; needs db-up)"
	@echo "  test-coverage   Run all tests with coverage report (term + html + xml)"
	@echo "  store-durations Record per-test timings into .test_durations"
	@echo "  diff-coverage   Run diff-cover against origin/main (fails if patch <90%)"
	@echo "  arch-check      Tach dependency contract + architecture fitness functions"
	@echo "  arch-show       Open the dependency graph (tach show)"
	@echo "  openapi-snapshot Regenerate apps/api/openapi.json from create_app()"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	cd $(API_DIR) && uv sync --all-extras

dev: db-up
	cd $(API_DIR) && uv run uvicorn aroc.api.main:app --reload --host 0.0.0.0 --port 8000

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) down

db-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres

lint:
	cd $(API_DIR) && uv run ruff check src tests
	cd $(API_DIR) && uv run ruff format --check src tests

fmt:
	cd $(API_DIR) && uv run ruff check --fix src tests
	cd $(API_DIR) && uv run ruff format src tests

typecheck:
	cd $(API_DIR) && uv run pyright src tests

# pytest-xdist with `--dist=worksteal -n 4`: worksteal is the scheduler of
# choice for mixed-duration suites (50ms unit alongside 200ms+ integration).
# `-n 4` matches a 4-core CI runner, and the suite is I/O-bound on per-worker
# Postgres, so more workers oversubscribe Docker and asyncpg rather than
# helping. Each worker brings up its own container (see tests/conftest.py).
#
# Kept out of `[tool.pytest.ini_options].addopts` so ad-hoc single-file runs
# stay sequential and avoid worker-spawn overhead. Make targets opt in.
PYTEST_PARALLEL := -n 4 --dist=worksteal

test:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL)

test-unit:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) -m unit

test-int:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) -m integration

test-contract:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) -m contract

# Local mirrors of the two CI test lanes (see .github/workflows/ci.yml).
# Path-based selection matches CI: it is the robust selector, since some
# helper and __init__ files carry no marker. test-noio starts no Postgres
# container (APP_ENV=test gives in-memory adapters); test-db needs `db-up`.
test-noio:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) tests/unit tests/architecture tests/contract

test-db:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) tests/integration tests/e2e

test-coverage:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) --cov --cov-report=term-missing --cov-report=html --cov-report=xml

# Record per-test execution times so pytest-split balances CI shards by time
# instead of by count. Runs the FULL suite (needs db-up) and writes
# apps/api/.test_durations; commit the result. Staleness costs shard balance,
# never correctness.
store-durations:
	cd $(API_DIR) && uv run pytest $(PYTEST_PARALLEL) --store-durations

diff-coverage:
	cd $(API_DIR) && uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=90

arch-check:
	cd $(API_DIR) && uv run tach check
	cd $(API_DIR) && uv run pytest tests/architecture

arch-show:
	cd $(API_DIR) && uv run tach show

# Regenerate the committed OpenAPI snapshot after intentional API surface
# changes. The drift test fails until this is run and the diff is reviewed.
openapi-snapshot:
	cd $(API_DIR) && APP_ENV=test uv run python -c "import json; from aroc.api.main import create_app; \
		f = open('openapi.json', 'w'); json.dump(create_app().openapi(), f, indent=2, sort_keys=True); f.write('\n'); f.close()"

precommit:
	cd $(API_DIR) && uv run pre-commit install
	cd $(API_DIR) && uv run pre-commit install --hook-type pre-push

precommit-run:
	cd $(API_DIR) && uv run pre-commit run --all-files

migrate-status:
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate status --env local

migrate-apply:
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate apply --env local

migrate-new:
	@if [ -z "$(name)" ]; then echo "Usage: make migrate-new name=add_foo"; exit 1; fi
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate new $(name)

migrate-hash:
	cd $(ATLAS_DIR) && atlas migrate hash

# `atlas migrate lint` moved behind atlas-cloud login in v0.38; this project
# deliberately skips that path. CI runs a narrow grep-based safety scan on new
# migrations instead (see .github/workflows/ci.yml). Locally, read your
# migration carefully and `make migrate-apply` against a scratch database
# before merging: that catches the same class of issues lint would flag.

clean:
	cd $(API_DIR) && rm -rf .pytest_cache .ruff_cache .pyright_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf site
