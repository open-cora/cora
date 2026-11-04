"""The trip out and the trip home read different settings, or they are one trip.

`infra/transferring/transfers.py` builds a transfer engine for either
direction, because `GlobusTransfer` is given its two collections when it
is built and a step may name neither. A chain that sends a dataset away
and brings the result back runs two of them in one process, and one
process holds one environment, so each direction reads its own family of
variables.

## Why this is a rule and not a convention

The wiring fault it refuses is invisible from every other angle.

`Repertoire` already refuses two engines offering one routine, so a pair
wired to the same name is a startup error. Nothing refuses a pair wired
to the same collections. A `HOMEWARD` that read `CORA_TRANSFER_SOURCE`
and `CORA_TRANSFER_DESTINATION` would build an engine pointing the same
way as the outbound one, answering to the routine that is supposed to
bring results home. It would submit a real task, Globus would complete
it, the step would succeed, and the record would say a result came back
to the beamline while the file went to the computing facility a second
time.

Nothing raises, the transfer is genuinely successful, and the only
evidence is a file that is not where the next person looks for it.

## Why the file is read rather than imported

Building either engine reaches a Globus client and a token store, and the
profile's two libraries are a deployment extra rather than a dev
dependency, so this suite cannot import the module at all. What is being
compared is a set of string literals either way.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROFILE = Path(__file__).resolve().parents[1] / "infra" / "transferring" / "transfers.py"

DIRECTIONS = ("OUTBOUND", "HOMEWARD")
"""The two this module declares, named so that losing one fails here."""

SETTINGS = ("source", "destination", "prefix", "routine", "settle")
"""Fields of `Direction` that hold the name of an environment variable.

`default_routine` is deliberately absent: it holds a routine name rather
than a variable name, and the directions are expected to differ in it
rather than merely not to collide.
"""


def _declared(name: str) -> dict[str, str]:
    """The keyword arguments of a module-level `name = Direction(...)`."""
    tree = ast.parse(PROFILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            raise AssertionError(f"{name} in {PROFILE.name} is no longer built by a call")
        return {
            keyword.arg: keyword.value.value
            for keyword in call.keywords
            if keyword.arg
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        }
    raise AssertionError(f"{PROFILE.name} no longer declares {name}")


def test_both_directions_are_declared_with_every_setting_named() -> None:
    """The guard on the comparisons below, which are the point of the file."""
    for name in DIRECTIONS:
        declared = _declared(name)
        missing = [field for field in (*SETTINGS, "default_routine") if field not in declared]
        assert not missing, (
            f"{name} in {PROFILE.name} names no {missing}, so the comparison "
            "below would pass over a setting the two directions might share."
        )


def test_the_two_directions_name_no_environment_variable_in_common() -> None:
    outbound, homeward = (_declared(name) for name in DIRECTIONS)
    shared = {
        field: outbound[field] for field in SETTINGS if outbound.get(field) == homeward.get(field)
    }

    assert not shared, (
        "The outbound and homeward transfer engines read the same variable "
        f"for {sorted(shared)}: {sorted(shared.values())}. One process holds "
        "one environment, so they would be built pointing the same way and "
        "the leg that is supposed to bring a result home would send it away "
        "again and report success."
    )


def test_the_two_directions_default_to_different_routines() -> None:
    outbound, homeward = (_declared(name) for name in DIRECTIONS)

    assert outbound["default_routine"] != homeward["default_routine"], (
        "Both transfer directions default to the routine "
        f"{outbound['default_routine']!r}. Repertoire refuses two engines "
        "offering one routine, so a deployment naming both profiles and "
        "overriding neither routine would fail at startup."
    )
