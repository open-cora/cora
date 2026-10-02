"""The keeper's words for how a step ended, copied into the thinker's thinking.

`apps/keeper/src/keeper/execution/aggregates/execution/state.py` declares
both vocabularies: `StepOutcome` for what the driver observed, `EngineState`
for what the engine said about itself. They travel to a client as strings and
arrive uninterpreted, which is deliberate on both sides.

`apps/thinker/infra/thinking/baseline.py` is the first thing on the thinker's
side that interprets them. It cannot import the keeper, for the mirror rule's
reason and for the reason every client here names a sibling's vocabulary with
a literal: it ships as its own repository and the keeper will not be beside
it. So it spells the words out.

Nothing else compares the two. Each project's suite enumerates its own
directory, so the keeper's tests cannot see the profile and the thinker's
cannot see the enumerations. This is the only check that reads both, which is
why it lives here.

## Why drift here is worse than loud failure

A renamed word does not raise anything. The table stops matching, every step
reads as a word it has no rule for, and the thinker abstains on everything
while staying up and answering every question it is asked. From outside that
is indistinguishable from a facility whose runs are all unremarkable.

The engine words are the sharper half. If those stop matching, a run whose
engine failed is read as a run that worked, and the profile concludes the
objective was met on data that was never taken.

## Why the words are read rather than imported

Importing would mean this tier installing both projects, and the tier
deliberately installs neither. What is being compared is a string literal
either way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[1]

DECLARED = (
    TREE
    / "apps"
    / "keeper"
    / "src"
    / "keeper"
    / "execution"
    / "aggregates"
    / "execution"
    / "state.py"
)
COPIED = TREE / "apps" / "thinker" / "infra" / "thinking" / "baseline.py"

OUTCOMES = "StepOutcome"
ENGINE_STATES = "EngineState"

COPIES: dict[str, tuple[str, str]] = {
    "DONE": (OUTCOMES, "DONE"),
    "BROKEN": (OUTCOMES, "BROKEN"),
    "ABORTED": (ENGINE_STATES, "ABORTED"),
    "FAILED": (ENGINE_STATES, "FAILED"),
}
"""Each name the profile binds, and the enumeration member it must equal.

Keyed by the profile's spelling rather than the keeper's, because the
profile is the copy and a reader arrives here from that side.
"""


def _enum_values(module: Path, enumeration: str) -> dict[str, str]:
    """Every `NAME = "Word"` inside one class, by member name."""
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ClassDef) or node.name != enumeration:
            continue
        for statement in node.body:
            match statement:
                case ast.Assign(
                    targets=[ast.Name(id=member)],
                    value=ast.Constant(value=str() as word),
                ):
                    found[member] = word
                case _:
                    continue
    return found


def _literals(module: Path) -> dict[str, str]:
    """Every module-level `NAME: Final = "Word"` the profile binds."""
    found: dict[str, str] = {}
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        match node:
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=str() as word)):
                found[name] = word
            case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str() as word)):
                found[name] = word
            case _:
                continue
    return found


@pytest.mark.parametrize("enumeration", (OUTCOMES, ENGINE_STATES))
def test_the_keeper_still_declares_the_enumeration_this_reads(enumeration: str) -> None:
    """Guard the lookup, so the comparison below cannot pass vacuously."""
    assert _enum_values(DECLARED, enumeration), (
        f"{DECLARED.name} no longer declares {enumeration} with string members. "
        "Renaming or moving it makes every comparison below range over nothing, "
        "which is the failure this test exists to prevent rather than to cause."
    )


def test_the_profile_still_binds_the_words_this_reads() -> None:
    """Guard the other side of the lookup, for the same reason."""
    bound = _literals(COPIED)
    missing = sorted(name for name in COPIES if name not in bound)
    assert not missing, (
        f"{COPIED.name} no longer binds {missing} to string literals. The "
        "comparison below then checks nothing, and the profile's words are "
        "unguarded exactly when somebody has just moved them."
    )


@pytest.mark.parametrize("name", sorted(COPIES))
def test_a_word_the_profile_spells_is_the_word_the_keeper_writes(name: str) -> None:
    enumeration, member = COPIES[name]
    declared = _enum_values(DECLARED, enumeration)
    assert member in declared, (
        f"{enumeration} no longer has a member {member}, which the thinker's "
        f"profile copies as {name}. Either the keeper renamed it, in which case "
        "the profile is now matching a word nothing sends, or this mapping is "
        "stale."
    )
    assert _literals(COPIED)[name] == declared[member], (
        f"the keeper writes {enumeration}.{member} as {declared[member]!r} and "
        f"the thinker's profile matches {_literals(COPIED)[name]!r}. The table "
        "stops recognising that word and the thinker abstains on every case it "
        "appears in, while staying up and answering every question it is asked."
    )
