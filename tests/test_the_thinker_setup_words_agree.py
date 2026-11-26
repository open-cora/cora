"""The keeper's words for a run that names a setup, copied into the thinker's thinking.

`apps/keeper/src/keeper/execution/aggregates/setup/state.py` declares them as
`SETUP_PARAMETERS`. An operation takes a setup when its parameters declare
every word in that set: a run of it names a setup by one, writes over some of
that setup's settings for the one run by the other, and is pinned at dispatch
to the setup's latest revision.

`apps/thinker/infra/thinking/setups.py` spells the same words as `CONFIG` and
`OVERRIDE`, and reads off them what a run was given, for both of the thinker's
profiles that weigh it. It cannot import the keeper, for the reason the words
for how a step ended are spelled out beside it: it ships as its own repository
and the keeper will not be there.

Nothing else compares the two. Each project's suite enumerates its own
directory, so the keeper's tests cannot see the thinker's literals and the
thinker's cannot see the keeper's set. This is the only check that reads both,
which is why it lives here.

## Why drift here is quiet

A renamed word raises nothing, and which of the two drifted decides what goes
wrong.

If the word a run names its setup by stops matching, every run that names one
reads as a run carrying its own values. The ladder finds no rung in a name and
an override and abstains on it, and the gateway profile shows a model the name
and the override and never the settings the run went out with.

If the override's word stops matching, every override is dropped and the
revision a run was pinned to reads as all it had. Both profiles then weigh the
revision's values wherever the override changed one, and the ladder writes the
next rung where the keeper does not look.

Either way the thinker stays up and answers every question it is asked.

## Why every word in the keeper's set has to be spelled

The words for how a step ended are a vocabulary the thinker reads part of: it
copies the ones it has a rule for and leaves the rest of each enumeration
unread on purpose, so the check on them asks only that each copied word is one
the keeper still writes.

This set is not a vocabulary to choose from. It is the keeper's definition of
what an operation declares when its runs name a setup, and an operation that
declares only part of it takes none. The thinker's reading of what such a run
was given is built from exactly those words, so a word joining the set is a
parameter every setup run then carries and the reading passes over, and the
thinker's answer for what a run had could be incomplete with nothing saying
so. The comparison therefore runs both ways, and a word the keeper adds fails
here until somebody decides how the thinker reads it. If one turns out to
change nothing about what a run had, the place to say so is this file, with
the reason, rather than a looser comparison.

## What it cannot see

The set does not say which word does which, so a thinker whose two words have
traded places passes here. That is a mistake inside one project rather than a
disagreement between two, and catching it falls to that project's own suite.

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
    TREE / "apps" / "keeper" / "src" / "keeper" / "execution" / "aggregates" / "setup" / "state.py"
)
COPIED = TREE / "apps" / "thinker" / "infra" / "thinking" / "setups.py"

PARAMETERS = "SETUP_PARAMETERS"

CONSEQUENCES: dict[str, str] = {
    "CONFIG": (
        "Every run that names a setup then reads as one carrying its own values: the ladder "
        "finds no rung in a name and an override and abstains on it, and the gateway profile "
        "shows a model the name and never the settings the run went out with."
    ),
    "OVERRIDE": (
        "Every override is then dropped and the revision a run was pinned to reads as all it "
        "had: both profiles weigh the revision's values wherever the override changed one, "
        "and the ladder writes the next rung where the keeper does not look."
    ),
}
"""Each name the thinker binds a setup word to, and what drift in that word does.

Keyed by the thinker's spelling rather than the keeper's, because the thinker
holds the copy and a reader arrives here from that side. The keeper's set could
not key it anyway: it holds the words without saying which does what.
"""


def _declaration(module: Path, name: str) -> ast.expr | None:
    """What a module binds `name` to at its top level, or None where it binds nothing."""
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        match node:
            case ast.AnnAssign(target=ast.Name(id=target), value=ast.expr() as value) if (
                target == name
            ):
                return value
            case ast.Assign(targets=[ast.Name(id=target)], value=value) if target == name:
                return value
            case _:
                continue
    return None


def _setup_parameters() -> frozenset[str]:
    """The words of the keeper's set, or an empty set where they are not written out.

    Empty rather than partial when any member is not a string literal, so a set
    built from names reads as one this cannot read rather than one missing a word.
    """
    match _declaration(DECLARED, PARAMETERS):
        case (
            ast.Set(elts=members)
            | ast.Call(
                func=ast.Name(id="frozenset"),
                args=[ast.Set(elts=members) | ast.Tuple(elts=members) | ast.List(elts=members)],
                keywords=[],
            )
        ):
            pass
        case _:
            return frozenset()
    words: list[str] = []
    for member in members:
        match member:
            case ast.Constant(value=str() as word):
                words.append(word)
            case _:
                return frozenset()
    return frozenset(words)


def _literals(module: Path) -> dict[str, str]:
    """Every module-level `NAME: Final = "word"` the thinker binds, by name."""
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


def test_the_keeper_still_declares_its_setup_parameters_as_string_literals() -> None:
    """Guard the lookup, so the comparison of the keeper's words cannot pass vacuously."""
    assert _setup_parameters(), (
        f"{DECLARED.relative_to(TREE)} no longer declares {PARAMETERS} as a set of string "
        "literals. Renaming it, moving it or building it from names leaves every word the "
        "keeper declares unread, so the check that the thinker spells each one passes on "
        "nothing, which is the failure this test exists to prevent rather than to cause."
    )


def test_the_thinker_still_binds_both_setup_words_to_string_literals() -> None:
    """Guard the other side, so a word that moved reads as moved rather than as drift."""
    bound = _literals(COPIED)
    missing = sorted(name for name in CONSEQUENCES if name not in bound)
    assert not missing, (
        f"{COPIED.relative_to(TREE)} no longer binds {missing} to string literals. If the "
        "words moved, point this check at their new home: until then the thinker's copy "
        "is unguarded exactly when somebody has just moved it."
    )


@pytest.mark.parametrize("name", sorted(CONSEQUENCES))
def test_a_word_the_thinker_spells_for_a_setup_run_is_one_the_keeper_declares(name: str) -> None:
    word = _literals(COPIED)[name]
    declared = _setup_parameters()
    assert word in declared, (
        f"the thinker spells {name} as {word!r}, and the keeper's {PARAMETERS} holds "
        f"{sorted(declared)}. {CONSEQUENCES[name]} Nothing raises, and the thinker stays up "
        "answering every question it is asked."
    )


def test_every_word_the_keeper_declares_for_a_setup_run_is_one_the_thinker_spells() -> None:
    bound = _literals(COPIED)
    spelled = {bound[name] for name in CONSEQUENCES if name in bound}
    unspelled = sorted(_setup_parameters() - spelled)
    assert not unspelled, (
        f"the keeper's {PARAMETERS} holds {unspelled}, which no word the thinker binds for a "
        "setup run spells. If the keeper renamed a word, the per-word check in this file says "
        "which of the thinker's words stopped matching. If it added one, every run that names "
        "a setup now carries a parameter the thinker's reading passes over, and its answer for "
        "what the run was given can be incomplete with nothing saying so."
    )
