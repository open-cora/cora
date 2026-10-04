"""A module that defines a type is named after it.

The keeper carries this rule and states the argument for it: the directories
it enforced were the only ones that stayed consistent, and every directory
it did not enforce drifted. The conductor is the evidence from the other
side, where a seam rename left an adapter module named for a Protocol that
no longer existed and nothing went red.

The rule is not that a filename carries a provider or a capability in an
agreed slot. It is that a reader who opens a file finds the type its name
promised. That is decidable, which is why it can be enforced, and being
enforced is the only property that has ever kept a directory consistent.

## What counts as a match

A module matches when a public type it defines snake-cases to:

  - the filename                  `case.py` -> `Case`
  - the folder plus the filename  `config.py` -> `ThinkerConfig`
  - the filename as a prefix or suffix of the type
  - the singular of a plural filename  `conclusions.py` -> `Conclusion`

The folder form is the one a trimmed copy of this rule would drop, because
nothing in this package looks like it needs a folder prefix. `ThinkerConfig`
sits in `thinker/config.py` and matches only through it, so dropping that
arm turns a correct module into an offender and makes the fix look like
renaming the config.

## Why a plural filename counts

This package names a module for a family and puts the family's members in
it. `conclusions.py` holds `Conclusion`. A plural matches its own singular
only, so the relaxation cannot pass a module holding an unrelated type.

## Why a type alias counts as a type

`Conclusion` is `Propose | Stop | Abstain | Refer` and not a class, and it
is exactly what `conclusions.py` is about. A rule that saw only class
statements would call that module nameless and push it into the exemptions
below, where a reader would find an entry claiming there is no subject
sitting next to the subject. The module needs both forms at once, which is
what makes it the case worth naming here.

## What the rule does not apply to

A module with no public type is a function namespace. There is no type to
be named after, and demanding one would invent a class per module. Error
and response classes are not the subject either, so a module exporting
functions and one error class is still a namespace.

That leaves modules that DO export public types and are still not about any
one of them. Those are declared below, and an entry costs a line of
reasoning.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from tests._tracked import PROJECT_ROOT, tracked_source_files

if TYPE_CHECKING:
    from pathlib import Path

NAMESPACE_MODULES: frozenset[str] = frozenset(
    {
        # Exports `think` plus `Thought`, which is what that function
        # returns. The module is the verb this package is named for, and
        # naming it for the result would name it for the smaller half of
        # what it is.
        "think.py",
        # The six outward seams. A family whose members are deliberately
        # unlike each other: there is no `Seam` type, because Protocols
        # sharing no verb have nothing to put on one.
        "seams.py",
    }
)
"""Modules that export a public type and are still not about one of them.

Separate from the automatic exemption for modules with no public type at
all. An entry here is a claim that the types present are a function's
arguments, its result, or a family with no head, rather than the module's
subject.
"""

_NOT_A_SUBJECT = ("Error", "Response")
"""Type-name suffixes that never make a module type-shaped.

Nearly every module here raises something, and the adapter describes the
HTTP response it reads. A module exporting one adapter and three error
classes is not a module about an error.
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


def _subject_types(tree: ast.Module) -> list[str]:
    """Public classes and type aliases defined at module level."""
    names: list[str] = []
    for node in tree.body:
        match node:
            case ast.ClassDef(name=str() as name):
                names.append(name)
            case ast.TypeAlias(name=ast.Name(id=str() as name)):
                names.append(name)
            case ast.AnnAssign(target=ast.Name(id=str() as name)) if _is_alias(node.value):
                names.append(name)
            case ast.Assign(targets=[ast.Name(id=str() as name)]) if _is_alias(node.value):
                names.append(name)
            case _:
                continue
    return [n for n in names if not n.startswith("_") and not n.endswith(_NOT_A_SUBJECT)]


def _is_alias(value: ast.expr | None) -> bool:
    """A union or a bare name on the right of an assignment is a type alias.

    `Conclusion = Propose | Stop` is one and `TIMEOUT_MARGIN_SECONDS = 5.0`
    is not. Reading the right-hand side is what separates them, because
    both are a name bound at module level and nothing else distinguishes
    the two.
    """
    match value:
        case ast.BinOp(op=ast.BitOr()):
            return True
        case ast.Name(id=str() as referenced):
            return referenced[:1].isupper()
        case ast.Subscript(value=ast.Name()):
            return True
        case _:
            return False


def _matches(type_name: str, path: Path) -> bool:
    snake = _snake(type_name)
    stem, folder = path.stem, path.parent.name
    return (
        snake == stem
        or snake == f"{folder}_{stem}"
        or snake.endswith(f"_{stem}")
        or snake.startswith(f"{stem}_")
        or (stem.endswith("s") and snake == stem[:-1])
    )


def test_every_module_defining_a_type_is_named_after_one_of_them() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_source_files()):
        relative = path.relative_to(PROJECT_ROOT / "src" / "thinker")
        if path.name == "__init__.py" or str(relative) in NAMESPACE_MODULES:
            continue
        types = _subject_types(ast.parse(path.read_text(encoding="utf-8")))
        if not types:
            continue
        if not any(_matches(name, path) for name in types):
            offenders.append(f"{relative}: defines {types}, named after none of them")
    assert not offenders, (
        "A module defining a public type must be named after one of them. Either "
        "rename the module to the type a reader will find in it, or add it to "
        "NAMESPACE_MODULES with a line saying why the types it holds are not its "
        "subject:\n  " + "\n  ".join(offenders)
    )


def test_every_namespace_module_entry_still_names_a_tracked_file() -> None:
    """An exemption outlives the file it was written for, and then hides a rule.

    A stale entry is worse than a missing one: it exempts nothing, so
    nothing fails, and the next module to take that path inherits an
    exemption written about a file that no longer exists.
    """
    source = PROJECT_ROOT / "src" / "thinker"
    missing = sorted(entry for entry in NAMESPACE_MODULES if not (source / entry).is_file())
    assert not missing, (
        "NAMESPACE_MODULES names files this project no longer has. Remove the "
        f"entry, or correct the path:\n  {chr(10).join(missing)}"
    )
