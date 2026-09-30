"""Two clients register datasets, and their retry keys have one shape.

The conductor files where its engine answered with a location and the
reporter files where a store resolved a name. Both send the keeper an
`Idempotency-Key` so that a restart mid-flight re-registers one address
into one record rather than two, and both build it from the address
alone, in a function each project holds its own copy of.

Nothing else compares them. Each project's suite enumerates its own
directory, per the mirror rule, so neither can see the other's spelling
and a change to one leaves every lane green.

## What actually breaks if they drift

Less than the keeper-id records, and worth being exact rather than
alarming. The keeper keys its cache on the principal as well as the key,
and these two clients are different principals, so their keys never meet
in that table and one drifting cannot collide with the other. Neither
client's own retry behaviour changes either, because each recomputes its
own spelling.

What breaks is the table a person reads when a dataset was registered
twice and nobody knows why. Two shapes of key naming one kind of thing
is the sort of thing that costs an afternoon years later, and the cost
of holding them together is this file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[1]

BUILDERS = (
    TREE / "apps" / "conductor" / "src" / "conductor" / "adapters" / "http_tasking.py",
    TREE / "apps" / "reporter" / "src" / "reporter" / "adapters" / "keeper_http.py",
)

FUNCTION = "dataset_key_for"
"""The function each project holds its own copy of.

Spelled the same in both because they were written to agree, not by any
rule, so a rename fails this rather than silently making it range over
nothing.
"""

HOLE = "{}"
"""What an interpolation is rewritten to before the two are compared.

The two functions take their argument under different names, and a
comparison of the source text would read that difference as a drift. It
is not one: what reaches the keeper is the literal text around the hole
and the value in it, and neither depends on what the parameter is
called.
"""


def _shape(source: Path) -> str:
    """The key that project builds, with its interpolations blanked out.

    Read rather than imported, because this tier installs neither
    project and importing the reporter's adapter would pull in an HTTP
    client. What is being compared is a literal either way.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == FUNCTION):
            continue
        returned = node.body[-1]
        assert isinstance(returned, ast.Return) and isinstance(returned.value, ast.JoinedStr), (
            f"{source.name}: {FUNCTION} no longer ends by returning an f-string, "
            "so this cannot read the shape it builds"
        )
        built: list[str] = []
        for part in returned.value.values:
            match part:
                case ast.Constant(value=str() as literal):
                    built.append(literal)
                case _:
                    built.append(HOLE)
        return "".join(built)
    raise AssertionError(f"{source.name} defines no {FUNCTION}")


@pytest.mark.parametrize("source", BUILDERS, ids=lambda p: f"{p.parents[2].name}/{p.name}")
def test_a_client_that_files_datasets_builds_its_retry_key_from_the_address(
    source: Path,
) -> None:
    """Guard the enumeration, and the one property the shape has to have.

    From the address rather than the step, because one run may write
    more than one dataset and a key naming the step would give both
    registrations one note. The second would come back holding the
    first's id and would never be recorded.
    """
    built = _shape(source)
    assert built == f"register-dataset:{HOLE}", (
        f"{source.name} builds its key as {built!r}, which is not the shape the "
        "other client uses. Both write into one table that a person reads."
    )


def test_both_clients_spell_one_dataset_key_the_same_way() -> None:
    """Said directly, rather than inferred from each matching a third thing.

    The check above compares each against a spelling written out here,
    which is a copy of the agreement rather than the agreement. Edited
    to match a drifting client, it would pass while the two differ.
    This one cannot: it reads both and compares them.
    """
    conductor, reporter = (_shape(source) for source in BUILDERS)
    assert conductor == reporter, (
        f"the conductor builds {conductor!r} and the reporter builds {reporter!r}, "
        "so one address reaches the keeper's retry table under two spellings"
    )
