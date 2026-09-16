"""A docstring may not name code or files that do not exist.

This repository was copied from a sibling codebase and stripped to its
chassis. The code that survived the strip compiles and is type-checked; its
prose was not checked by anything, so docstrings kept describing classes,
functions, migrations and design documents that came across only as names.
A reader cannot tell the difference between a name they have not found yet
and a name that is not there, so every such reference costs a search that
ends in nothing.

Three rules, all decidable:

  - A backticked CamelCase name in a docstring must be defined somewhere in
    `src/` or `tests/`, or be declared in `EXTERNAL_NAMES` below.
  - So must a backticked SCREAMING_SNAKE constant or a backticked
    leading-underscore private name. Both were outside the first version
    of this check, which keyed on CamelCase alone. The omission cost the
    review that found it: one docstring named two constants and a private
    helper that this repository has never defined, and read as green
    through the whole infrastructure sweep.
  - A file path cited in a docstring must exist in the repository.

Neither rule can see a wrong explanation of a real symbol. They catch the
cheaper failure: prose that refers to nothing at all.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import ast
import builtins
import itertools
import re
from pathlib import Path

import pytest

from tests.architecture.conftest import tracked_python_files, tracked_test_files

pytestmark = pytest.mark.architecture

_REPO_ROOT = Path(__file__).resolve().parents[4]

EXTERNAL_NAMES: frozenset[str] = frozenset(
    {
        # Postgres
        "AccessExclusiveLock",
        # asyncpg
        "PoolConnectionProxy",
        "Record",
        # starlette / fastapi / mcp
        "ServerErrorMiddleware",
        "Context",
        # typing / stdlib
        "Coroutine",
        "CoroutineType",
        "TypeAlias",
        # HTTP header names
        "Host",
        "Authorization",
        # OpenTelemetry environment variables, read by the SDK itself
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    }
)
"""CamelCase names that are real but defined outside this repository.

Declared rather than pattern-matched: an unknown name is a defect by
default, and admitting one should cost a line of evidence. Python builtins
are admitted separately since `dir(builtins)` already enumerates them.
"""

PROSPECTIVE_NAMES: frozenset[str] = frozenset(
    {
        # Shapes the first bounded context should take. Named here before
        # anything defines them, which is the point: the docstring is telling
        # a future author what to call the thing, not citing one that exists.
        "Handler",
        "Item",
        "Page",
        "SurfaceKind",
        # Worked examples inside docstring code blocks, standing in for the
        # per-aggregate value object each BC will declare for itself.
        "ActorName",
        "MethodName",
        "PolicyName",
        # Alternatives considered and rejected. The prose exists to say why
        # they are absent, so requiring them to be present inverts it.
        "BoundedText",
        "Builder",
        "Llm",
        "TestDatabase",
        "Test",
        # The per-value-object length bound each aggregate declares in its
        # own state module. `aroc.shared.bounded_text` describes the
        # convention; no aggregate exists yet to hold one.
        "MAX_LENGTH",
    }
)
"""Names this repository deliberately does not define.

Distinct from `EXTERNAL_NAMES`, which are real elsewhere. These are real
nowhere: a shape a future slice should adopt, a stand-in inside a worked
example, or an alternative the prose rejects by name. Each still costs a
line here, so an entry is a decision rather than a way past the check.
"""

_CAMEL_CASE = re.compile(r"`([A-Z][a-zA-Z0-9]*[a-z][a-zA-Z0-9]*)`")
_CONSTANT = re.compile(r"`(_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")
"""A backticked constant, with or without a leading underscore.

At least one underscore is required, which is what keeps SQL and protocol
words out: `CHECK`, `NULL` and `POST` carry none, while every constant this
codebase declares carries at least one."""

_PRIVATE = re.compile(r"`(_[a-z][A-Za-z0-9_]*)`")
"""A backticked module-private function or variable.

Worth checking precisely because it is private: a reader cannot resolve it
by importing, only by finding it, and there is nowhere else to look."""
_FILE_PATH = re.compile(r"`?\b([A-Za-z0-9_./-]+\.(?:py|sql|md|toml|yml|yaml|hcl|cff))\b`?")
_MIGRATION = re.compile(r"\b(20\d{12}_[a-z0-9_]+)")
"""An Atlas migration cited without its `.sql` suffix.

A separate pattern because the path regex keys on the extension, and the
timestamped name reads as a version rather than a file. One such reference
survived the first sweep for exactly that reason."""


def _all_python_files() -> list[Path]:
    return sorted(tracked_python_files() | tracked_test_files())


def _defined_names() -> frozenset[str]:
    """Every name this repository binds anywhere: classes, functions, module
    stems, assignments, parameters, attributes, and imported symbols.

    Deliberately over-inclusive. The rule is about prose that refers to
    nothing, so the cost of admitting a name that exists in some other sense
    is far lower than the cost of a false failure on a real one.
    """
    names = set(dir(builtins)) | EXTERNAL_NAMES | PROSPECTIVE_NAMES
    for path in _all_python_files():
        names.add(path.stem)
        for node in ast.walk(ast.parse(path.read_text())):
            match node:
                case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                    names.add(node.name)
                case ast.Name(ctx=ast.Store()):
                    names.add(node.id)
                case ast.arg():
                    names.add(node.arg)
                case ast.Attribute():
                    names.add(node.attr)
                case ast.Constant(value=str() as text):
                    # A string literal in the same file makes the name real:
                    # event-type discriminants, `Literal[...]` arms and dict
                    # keys are code, even though they are not definitions.
                    names.add(text)
                case ast.TypeVar():
                    names.add(node.name)
                case ast.Import() | ast.ImportFrom():
                    names.update((a.asname or a.name).split(".")[-1] for a in node.names)
                case _:
                    pass
    return frozenset(names)


def _docstrings(path: Path) -> list[str]:
    """Every docstring in the file, including attribute docstrings.

    `ast.get_docstring` covers modules, classes and functions. It does not
    cover the bare string after an assignment (PEP 258), which this codebase
    uses for constants: `NOTIFY_CHANNEL`, `SIGNED_EVENT_TYPES`, the readiness
    budgets. Those are 31 docstrings that went unchecked until a mutation
    planted in one of them survived.
    """
    tree = ast.parse(path.read_text())
    docs = [
        doc
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        if (doc := ast.get_docstring(node))
    ]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for assignment, following in itertools.pairwise(body):
            if not isinstance(assignment, ast.Assign | ast.AnnAssign):
                continue
            match following:
                case ast.Expr(value=ast.Constant(value=str() as text)):
                    docs.append(text)
                case _:
                    pass
    return docs


def test_docstring_class_names_resolve_to_a_definition_in_the_tree() -> None:
    defined = _defined_names()
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            cited = _CAMEL_CASE.findall(doc) + _CONSTANT.findall(doc)
            cited += _PRIVATE.findall(doc)
            for name in cited:
                if name not in defined:
                    unresolved.append(f"{path.relative_to(_REPO_ROOT)}: `{name}`")
    assert not unresolved, (
        "Docstrings name symbols that are defined nowhere in src/ or "
        "tests/. Either the symbol was left behind when this repo was stripped "
        "(rewrite the prose), or it is real and external (add it to "
        "EXTERNAL_NAMES with a comment saying where it lives):\n  "
        + "\n  ".join(sorted(unresolved))
    )


def test_docstring_file_citations_resolve_to_a_path_in_the_repo() -> None:
    unresolved: list[str] = []
    for path in _all_python_files():
        for doc in _docstrings(path):
            for line in doc.splitlines():
                # A URL is a citation of someone else's tree, not of ours.
                if "http" in line or re.search(r"\b[a-z0-9-]+\.(?:com|org|io|net)/", line):
                    continue
                for cited in _FILE_PATH.findall(line) + [
                    f"{stem}.sql" for stem in _MIGRATION.findall(line)
                ]:
                    basename = cited.split(":")[0].split("/")[-1]
                    if not any(_REPO_ROOT.rglob(basename)):
                        unresolved.append(f"{path.relative_to(_REPO_ROOT)}: {cited}")
    assert not unresolved, (
        "Docstrings cite files that do not exist in this repository. A reader "
        "cannot follow them, so the claim they support cannot be checked:\n  "
        + "\n  ".join(sorted(unresolved))
    )
