"""A module that defines a type is named after it.

`ports/` and `adapters/` were the only two directories in this package whose
filenames matched their contents perfectly, and they were the only two with a
fitness test saying so. Everywhere else drifted: a module named for a
configuration that defined a settings class, a module named for a handler
that defined no handler, a module whose filename abbreviated a class name
its siblings spelled out. The correlation between "enforced" and
"consistent" is the argument for this file. Renaming without a check just
restarts the clock.

## What counts as a match

A module matches when any public class it defines snake-cases to:

  - the filename                      `kernel.py`     -> `Kernel`
  - the folder plus the filename      `projection/worker.py` -> `ProjectionWorker`
  - the filename as a prefix or       `projection/wakeup.py` -> `WakeupSource`
    suffix of the class

The folder-prefix form is the one worth naming. A directory already supplies
a category, so repeating it in the filename says it twice. Letting the
folder carry the prefix is what allowed the modules under `slices/` to drop
the qualifiers they were carrying at the package root.

## What the rule does not apply to

A module with no public class is a function namespace: `logging.py`,
`pool.py`, `deps.py`. There is no type to be named after, and demanding one
would invent a class per module. Error and response classes do not count as
the subject either, so a module exporting three functions and one error
class is still a namespace.

That leaves a small set of modules that DO export subject types and are
still namespaces, because the types are a function's parameters or its
result rather than the point of the module. Those are declared below, and
declaring one costs a line of reasoning.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

NAMESPACE_MODULES: frozenset[str] = frozenset(
    {
        # Exports `make_list_query_handler` plus the filter types that are its
        # arguments. Naming the module after one filter would be arbitrary.
        "infrastructure/slices/listing.py",
    }
)
"""Modules that export a public type and are still function namespaces.

Separate from the automatic exemption for modules with no public class at
all. An entry here is a claim that the types present are a function's
parameters or its result, not the module's subject.
"""

_NOT_A_SUBJECT = ("Error", "Response")
"""Class-name suffixes that never make a module class-shaped.

Nearly every namespace module raises something. A module exporting four
functions and one error class is not a module about that error.
"""


def _snake(name: str) -> str:
    out: list[str] = []
    for i, char in enumerate(name):
        boundary = (
            char.isupper()
            and i > 0
            and not (name[i - 1].isupper() and (i + 1 >= len(name) or name[i + 1].isupper()))
        )
        if boundary:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _subject_classes(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        if not node.name.startswith("_")
        if not node.name.endswith(_NOT_A_SUBJECT)
    ]


def _matches(class_name: str, path: Path) -> bool:
    snake = _snake(class_name)
    stem, folder = path.stem, path.parent.name
    return (
        snake == stem
        or snake == f"{folder}_{stem}"
        or snake.endswith(f"_{stem}")
        or snake.startswith(f"{stem}_")
    )


def test_every_module_defining_a_type_is_named_after_one_of_them() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_python_files()):
        if path.name == "__init__.py":
            continue
        relative = str(path).split("src/aroc/", 1)[-1]
        if relative in NAMESPACE_MODULES:
            continue
        classes = _subject_classes(ast.parse(path.read_text()))
        if not classes:
            continue
        if not any(_matches(name, path) for name in classes):
            offenders.append(f"{relative}: defines {', '.join(classes)}")
    assert not offenders, (
        "Modules whose filename names none of the types they define. Rename the "
        "file to its subject, let the folder carry the category, or add it to "
        "NAMESPACE_MODULES with the reason its types are not its subject:\n  "
        + "\n  ".join(offenders)
    )


def test_every_declared_namespace_module_still_exists_and_still_needs_the_entry() -> None:
    """A stale exemption is worse than none: it reads as a considered decision
    while covering a file that has moved or has since been renamed correctly."""
    tracked = {str(p).split("src/aroc/", 1)[-1] for p in tracked_python_files()}
    missing = sorted(NAMESPACE_MODULES - tracked)
    assert not missing, f"NAMESPACE_MODULES names files that no longer exist: {missing}"

    unnecessary: list[str] = []
    for relative in sorted(NAMESPACE_MODULES):
        path = next(p for p in tracked_python_files() if str(p).endswith(relative))
        classes = _subject_classes(ast.parse(path.read_text()))
        if not classes or any(_matches(name, path) for name in classes):
            unnecessary.append(relative)
    assert not unnecessary, (
        f"NAMESPACE_MODULES entries that would now pass on their own; drop them: {unnecessary}"
    )
