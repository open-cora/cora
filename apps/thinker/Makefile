.PHONY: install lint fmt typecheck test docs-serve docs-build \
        precommit precommit-run clean help

# One project, one lockfile, one virtualenv. Every target runs here rather
# than looping over a tree, which is the difference between this Makefile and
# the root one that delegates to it.
# Every tracked Python file in the project, not a list of the directories
# somebody remembered. Each of these was a hand-written list once, and
# each had Python outside it: the conductor's simulator, the keeper's two
# deploy scripts, the reporter's two collectors. A simulator shipped a
# docstring citing a test file that has never existed in any branch, and
# no lane here was looking at it. ruff honours the ignore rules, so the
# virtualenv and the built site stay out without being named.
STYLED := .

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv"
	@echo "  lint            Run ruff check + format check"
	@echo "  fmt             Run ruff format and auto-fix"
	@echo "  typecheck       Run pyright, strict"
	@echo "  test            Run the suite"
	@echo "  docs-serve      Serve the docs site at http://127.0.0.1:8025"
	@echo "  docs-build      Build the docs site, strict"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	uv sync

lint:
	uv run ruff check $(STYLED)
	uv run ruff format --check $(STYLED)

fmt:
	uv run ruff check --fix $(STYLED)
	uv run ruff format $(STYLED)

# `infra` is in here and not in the sibling projects' lanes because what it
# holds is different: theirs ship simulators and collectors, and this one
# ships the profile that satisfies the inference seam. That file's claim to
# satisfy it is structural, the entrypoint casts rather than checks, and a
# type checker is the only thing that can read the claim before a
# deployment does.
typecheck:
	uv run pyright src tests infra

test:
	uv run pytest

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
	$(MKDOCS) serve -a 127.0.0.1:8025

# `--strict` is what makes a broken cross-link fail rather than warn.
docs-build:
	$(MKDOCS) build --strict
