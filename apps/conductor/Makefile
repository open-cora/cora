.PHONY: install lint fmt typecheck test test-core docs-serve docs-build \
        precommit precommit-run clean help

# One project, one lockfile, one virtualenv. Every target runs here rather
# than looping over a tree, which is the difference between this Makefile and
# the one it was split out of.
STYLED := src tests typings

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv, extras included"
	@echo "  lint            Run ruff check + format check"
	@echo "  fmt             Run ruff format and auto-fix"
	@echo "  typecheck       Run pyright, strict"
	@echo "  test            Run the whole suite, soft IOC included"
	@echo "  test-core       Run everything that needs no Channel Access socket"
	@echo "  docs-serve      Serve the docs site at http://127.0.0.1:8022"
	@echo "  docs-build      Build the docs site, strict"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	uv sync --all-extras

lint:
	uv run ruff check $(STYLED)
	uv run ruff format --check $(STYLED)

fmt:
	uv run ruff check --fix $(STYLED)
	uv run ruff format $(STYLED)

typecheck:
	uv run pyright src tests

# The whole suite, which starts a caproto soft IOC and drives simulated
# motors through real Channel Access. About ninety seconds, and it is what
# CI runs.
test:
	uv run pytest

# Everything that does not need the socket. The IOC still starts, because the
# fixture serving it is session-scoped and autouse, so this saves the motor
# travel rather than the startup.
test-core:
	uv run pytest -m "not channel_access"

precommit:
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

precommit-run:
	uv run pre-commit run --all-files

clean:
	rm -rf .pytest_cache .ruff_cache .pyright_cache build dist *.egg-info site
	find . -type d -name __pycache__ -exec rm -rf {} +

# The docs toolchain is not a project dependency: it is pulled per-invocation
# with `uv run --with`, pinned here so two machines render the same site.
MKDOCS := uv run --with mkdocs-material==9.7.7 mkdocs

docs-serve:
	$(MKDOCS) serve -a 127.0.0.1:8022

# `--strict` is what makes a broken cross-link fail rather than warn.
docs-build:
	$(MKDOCS) build --strict
