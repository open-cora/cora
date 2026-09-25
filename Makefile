.PHONY: install lint fmt typecheck test \
        tree-install tree-lint tree-fmt tree-typecheck tree-test \
        test-unit test-int test-contract test-noio test-db test-coverage \
        diff-coverage arch-check arch-show dev db-up db-down db-reset \
        migrate-status migrate-apply migrate-new migrate-hash \
        refresh-captures docs-serve docs-build precommit precommit-run \
        clean help

# CORA is one development tree holding projects that ship apart. Each
# directory under apps/ is a complete repository, with its own lockfile, its
# own Makefile and its own CI workflow, and is published as a mirror.
#
# So this Makefile orchestrates and defines nothing an app's own Makefile
# defines. Every lane below delegates with `make -C`, which is what keeps one
# spelling of a lane rather than one here and one over there: a lane that
# drifted would run something different depending on which directory you
# started in, and the mirror would run the other one.
APPS := apps/keeper apps/conductor apps/reporter

KEEPER_DIR := apps/keeper
REPORTER_DIR := apps/reporter

# What belongs to no project: `beamlines/`, which describes a facility rather
# than a system, and `tests/`, the checks that range over more than one of
# them. This is the tree's own lane, and it exists because those two were in
# none: unlinted, untypechecked, and tested only when somebody typed it.
TREE_STYLED := tests beamlines

help:
	@echo "CORA: one development tree, projects that ship apart."
	@echo
	@echo "Every app (apps/keeper, apps/conductor, apps/reporter):"
	@echo "  install         Install Python deps via uv, in every app"
	@echo "  lint            Run ruff check + format check, in every app"
	@echo "  fmt             Run ruff format and auto-fix, in every app"
	@echo "  typecheck       Run pyright, strict, in every app"
	@echo "  test            Run every app's suite, and this tier's"
	@echo "  clean           Remove caches and build artefacts"
	@echo
	@echo "The keeper (delegated to apps/keeper):"
	@echo "  dev             Run FastAPI dev server (reload, :8000)"
	@echo "  db-up           Start Postgres + pgvector via Docker Compose"
	@echo "  db-down         Stop Postgres"
	@echo "  db-reset        Stop Postgres and wipe its volume"
	@echo "  migrate-status  Show pending migrations against local DB"
	@echo "  migrate-apply   Apply pending migrations to local DB"
	@echo "  migrate-new     Generate a new migration skeleton (name=<short_name>)"
	@echo "  migrate-hash    Recompute atlas.sum after editing migrations by hand"
	@echo "  test-unit       Run only unit tests"
	@echo "  test-int        Run only integration tests"
	@echo "  test-contract   Run only contract tests"
	@echo "  test-noio       Run the no-DB CI lane (unit + architecture + contract)"
	@echo "  test-db         Run the DB CI lane (integration + e2e; needs db-up)"
	@echo "  test-coverage   Run all tests with coverage report (term + html + xml)"
	@echo "  diff-coverage   Run diff-cover against origin/main (fails if patch <90%)"
	@echo "  arch-check      Tach dependency contract + architecture fitness functions"
	@echo "  arch-show       Open the dependency graph (tach show)"
	@echo
	@echo "The reporter (delegated to apps/reporter):"
	@echo "  refresh-captures Re-record the fixtures from a real engine and store"
	@echo
	@echo "This tree's own (beamlines/ and tests/, which belong to no project):"
	@echo "  tree-lint       Run ruff over tests and beamlines"
	@echo "  tree-typecheck  Run pyright, strict, over tests and beamlines"
	@echo "  tree-test       Run the cross-cutting checks and the beamline tests"
	@echo
	@echo "This tree:"
	@echo "  docs-serve      Serve the CORA site at http://127.0.0.1:8021"
	@echo "  docs-build      Build the CORA site and every app's, strict"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"

# One recipe, bound to `$@` per target: each of these exists in every app's
# Makefile under the same name, so the root runs the app's own definition
# rather than a second copy of it. The tree's own lane runs first, because a
# failure in a shared rule is the one worth seeing before three suites scroll
# past it.
install lint fmt typecheck test:
	@echo "==> . (the tree)"
	@$(MAKE) --no-print-directory tree-$@
	@for app in $(APPS); do \
		echo "==> $$app"; \
		$(MAKE) --no-print-directory -C $$app $@ || exit 1; \
	done

tree-install:
	uv sync

tree-lint:
	uv run ruff check $(TREE_STYLED)
	uv run ruff format --check $(TREE_STYLED)

tree-fmt:
	uv run ruff check --fix $(TREE_STYLED)
	uv run ruff format $(TREE_STYLED)

tree-typecheck:
	uv run pyright $(TREE_STYLED)

# `tests/` and `beamlines/tests/` together; pyproject names both as testpaths.
tree-test:
	uv run pytest

# Targets only the keeper has: its database, its migrations, its tiers and
# its dependency graph. `name=` on a `migrate-new` command line reaches the
# sub-make on its own, because make passes command-line variables down.
dev db-up db-down db-reset migrate-status migrate-apply migrate-new migrate-hash \
test-unit test-int test-contract test-noio test-db test-coverage diff-coverage \
arch-check arch-show:
	$(MAKE) --no-print-directory -C $(KEEPER_DIR) $@

# Only the reporter records fixtures from a live engine and store.
refresh-captures:
	$(MAKE) --no-print-directory -C $(REPORTER_DIR) $@

clean:
	@for app in $(APPS); do \
		$(MAKE) --no-print-directory -C $$app clean || exit 1; \
	done
	rm -rf site .pytest_cache .ruff_cache .pyright_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# The docs toolchain is not a project dependency: it is pulled per-invocation
# with `uv run --with`, pinned here so two machines render the same site. The
# pin is repeated in each app's Makefile, because each app builds its own site
# in its own repository and cannot read this one.
MKDOCS := uv run --with mkdocs-material==9.7.7 mkdocs

# One site per repository. This one is CORA's, saying what the projects are
# and how they fit; each app carries the pages that bind it and builds its
# own. `--strict` is what makes a broken cross-link fail rather than warn, and
# dividing docs/ is exactly the change that breaks cross-links.
docs-serve:
	$(MKDOCS) serve -a 127.0.0.1:8021

docs-build:
	$(MKDOCS) build --strict
	@for app in $(APPS); do \
		echo "==> $$app"; \
		$(MAKE) --no-print-directory -C $$app docs-build || exit 1; \
	done

# Run from this directory so pre-commit reads THIS tree's config, which is the
# one covering every app at once. It used to borrow the keeper's environment
# for the tool; the tree has its own now. Each app installs its own hooks from
# its own directory, for the clone its mirror becomes.
precommit:
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

precommit-run:
	uv run pre-commit run --all-files
