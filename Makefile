.PHONY: install dev db-up db-down db-reset lint typecheck test test-unit test-int \
        test-contract test-noio test-db test-coverage diff-coverage \
        docs-serve docs-build refresh-captures \
        fmt clean help migrate-status migrate-apply migrate-new migrate-hash \
        precommit precommit-run arch-check arch-show

API_DIR := apps/api
# The reporter is a separate deployable with its own lockfile, so every
# lane below runs twice rather than over a shared tree. Two projects does
# not justify a loop; a third would.
REPORTER_DIR := apps/reporter
COMPOSE := docker compose -f infra/docker-compose.yml
ATLAS_DIR := infra/atlas
LOCAL_DB_URL ?= postgres://aroc:aroc@localhost:5433/aroc?sslmode=disable

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv (apps/api and apps/reporter)"
	@echo "  refresh-captures Re-record the reporter fixtures from a real engine and store"
	@echo "  dev             Run FastAPI dev server (reload, :8000)"
	@echo "  db-up           Start Postgres + pgvector via Docker Compose"
	@echo "  db-down         Stop Postgres"
	@echo "  db-reset        Stop Postgres and wipe its volume"
	@echo "  migrate-status  Show pending migrations against local DB"
	@echo "  migrate-apply   Apply pending migrations to local DB"
	@echo "  migrate-new     Generate a new migration skeleton (name=<short_name>)"
	@echo "  migrate-hash    Recompute atlas.sum after editing migrations by hand"
	@echo "  lint            Run ruff check + format check (both projects)"
	@echo "  fmt             Run ruff format and auto-fix (both projects)"
	@echo "  typecheck       Run pyright, strict (both projects)"
	@echo "  test            Run all tests (both projects)"
	@echo "  test-unit       Run only unit tests"
	@echo "  test-int        Run only integration tests"
	@echo "  test-contract   Run only contract tests"
	@echo "  test-noio       Run the no-DB CI lane (unit + architecture + contract)"
	@echo "  test-db         Run the DB CI lane (integration + e2e; needs db-up)"
	@echo "  test-coverage   Run all tests with coverage report (term + html + xml)"
	@echo "  docs-serve      Serve the docs site at http://127.0.0.1:8021"
	@echo "  docs-build      Build the docs site, strict, into site/"
	@echo "  diff-coverage   Run diff-cover against origin/main (fails if patch <90%)"
	@echo "  arch-check      Tach dependency contract + architecture fitness functions"
	@echo "  arch-show       Open the dependency graph (tach show)"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	cd $(API_DIR) && uv sync --all-extras
	cd $(REPORTER_DIR) && uv sync

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
	cd $(REPORTER_DIR) && uv run ruff check src tests typings
	cd $(REPORTER_DIR) && uv run ruff format --check src tests typings

fmt:
	cd $(API_DIR) && uv run ruff check --fix src tests
	cd $(API_DIR) && uv run ruff format src tests
	cd $(REPORTER_DIR) && uv run ruff check --fix src tests typings
	cd $(REPORTER_DIR) && uv run ruff format src tests typings

typecheck:
	cd $(API_DIR) && uv run pyright src tests
	cd $(REPORTER_DIR) && uv run pyright src tests

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
	cd $(REPORTER_DIR) && uv run pytest

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

# diff-cover against the merge base, at a stricter bar than the suite-wide
# floor in pyproject.toml. Local only: no CI lane runs it, so it is a check an
# author chooses, not one a pull request has to clear.
diff-coverage:
	cd $(API_DIR) && uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=90

arch-check:
	cd $(API_DIR) && uv run tach check
	cd $(API_DIR) && uv run pytest tests/architecture

arch-show:
	cd $(API_DIR) && uv run tach show

# There is no committed OpenAPI snapshot and no target to write one. What
# guards the surface is EXPECTED_OPENAPI_PATHS in
# apps/api/tests/contract/test_app_surfaces.py, which pins the published path
# set and fails when a slice lands or retires a route.
#
# Scope it honestly: that catches a route appearing or vanishing, not a
# response model changing shape. Catching the second needs a committed
# document and a test that diffs against it, and neither exists. A target that
# regenerated a file nothing reads used to stand here and claimed a drift test
# that was never written.

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

# The docs toolchain is not a project dependency: it is pulled per-invocation
# with `uv run --with`, pinned here so two machines render the same site.
# Promote it to a dependency group when something other than a person needs
# to build the docs, such as a publishing workflow.
MKDOCS := uv run --with mkdocs-material==9.7.7 mkdocs

docs-serve:
	$(MKDOCS) serve -a 127.0.0.1:8021

docs-build:
	$(MKDOCS) build --strict

# Re-record what a real engine and a real store actually do, into the two
# fixtures the reporter's suite asserts against.
#
# Deliberately unpinned. Installing the versions the findings were written
# against would make this incapable of discovering anything: same input,
# same output, green forever. Latest is the point.
#
# Do NOT commit the result on a whim. Ids and timestamps change every run,
# so the diff is almost all noise and a habit of committing it teaches
# everyone to ignore capture diffs. What to read is whether the suite
# still passes afterwards: the assertions are written against the
# structural claims, so a red test names the finding that moved. Commit
# the new capture only as part of reacting to one.
#
# Neither collector can run under a project. Both import an engine, and
# the store's client picks up the wrong httpx beside apps/api. That is why
# these are two long invocations rather than a lane.
refresh-captures:
	uv run --no-project --python 3.13 \
	    --with bluesky --with ophyd \
	    python spikes/bluesky_adapter/collect.py
	uv run --no-project --python 3.13 \
	    --with 'tiled[server,client]' --with bluesky --with ophyd \
	    python spikes/tiled_adapter/collect.py
	@echo
	@echo "Captures refreshed. Now run: make test"
	@echo "A red test names the finding that moved; the diff is mostly noise."

