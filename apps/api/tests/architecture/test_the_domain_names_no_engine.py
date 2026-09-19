"""The domain and its docs name no particular engine.

A run happens in whatever engine a deployment runs, and this context holds
a record of what that engine did. Which engine is a deployment's fact, not
a modelling one: `Identifier`'s scheme half is open for exactly that
reason, and the state module says so.

Prose can leak what the types do not. Three sentences in the Execution
page justified domain rules by naming one engine, saying that it offers
three ways to stop a paused run, that its documents carry a timestamp, and
what it calls a cooperative pause. Every one of those was true and
load-bearing as evidence, and every one of them read as though the model
had been derived from a vendor.

## What is banned, and where

Documentation pages and the source tree. An engine name in either is a
claim, and the claim is wrong in the same way whether or not the fact
behind it is right: the rule holds for any engine, and naming one says a
second would need a second rule.

## What is not banned, and why each is different

**The spike.** `spikes/` is the record of driving one real engine into
this surface, so it names that engine on every page. It is also marked for
deletion when a real adapter lands. Engine facts belong on the adapter
side of a port, and the spike is where that side lives today.

It is outside the scanned set by construction rather than by exception:
the two enumerators below reach `src/aroc` and `docs` and nothing else.
Widening either one is the moment to add a real exclusion, and until then
an exclusion here would be a filter that has never removed anything.

**Test data.** Tests pass a scheme string like an engine's name into an
open-scheme field, which is a value rather than an assertion. A test
needs some concrete string and a realistic one reads better than a
placeholder, and nothing about it says the model assumes that engine.

This is the difference from `test_no_sibling_project_vocabulary.py` next
door, which scans tests as well: that rule bans a vocabulary, a word
meaning something only in a tree this one does not model, so a hit
anywhere is a defect. This rule bans a claim, and data makes none.

**Design precedents.** Naming Temporal or Step Functions as the shape
somebody else settled on is a citation, not an assumption about what runs
here. Only engine names are listed below.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import (
    REPO_ROOT,
    tracked_markdown_files,
    tracked_python_files,
)

pytestmark = pytest.mark.architecture

ENGINE_TERMS: frozenset[str] = frozenset(
    {
        # The engine the first adapter will speak to, and the three
        # projects around it that a reader would take for the same claim.
        "bluesky",
        "ophyd",
        "databroker",
        "runengine",
        # The control system underneath it. Less likely to be reached for
        # and more damaging if it is, because a control system is further
        # from anything this context models than the engine is.
        "epics",
    }
)
"""Engine names a domain page or a source file may not use.

An entry earns its place by naming a particular product this deployment
might run, rather than a kind of thing the model is about. Removing one
would mean this project had decided to model that product, which is a
decision worth making on purpose and against the layering.
"""

_TERM_PATTERN = re.compile(rf"\b(?:{'|'.join(sorted(ENGINE_TERMS))})\b", re.IGNORECASE)

_THIS_FILE = "test_the_domain_names_no_engine.py"


def find_engines(text: str) -> list[tuple[int, str]]:
    """Every line of `text` naming a listed engine, as (line number, line).

    Takes the text rather than a path so the check below can be shown to
    fire against input of the caller's choosing, the tree being clean.
    """
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if _TERM_PATTERN.search(line)
    ]


def _scanned_files() -> list[Path]:
    """Tracked source and documentation, minus this file.

    This file has to name what it refuses, so scanning it would fail on
    its own list.
    """
    return sorted(
        path
        for path in tracked_python_files() | tracked_markdown_files()
        if path.name != _THIS_FILE
    )


def test_the_engine_scan_covers_source_and_documentation() -> None:
    """Guard the enumeration: an empty file set makes the rule vacuous."""
    scanned = _scanned_files()
    assert any(path.suffix == ".py" for path in scanned), "No source file scanned."
    assert any(path.suffix == ".md" for path in scanned), "No documentation scanned."


def test_the_scanner_finds_an_engine_and_leaves_ordinary_prose_alone() -> None:
    """The second half matters as much as the first. A scanner keyed on
    substrings would hit `blueskies` and any word ending in `epic`, and a
    rule that fires on ordinary prose gets excepted into uselessness."""
    hits = find_engines("as Bluesky does it\nand a clean line\n")
    assert hits == [(1, "as Bluesky does it")]

    assert find_engines("the EPICS record underneath")
    assert not find_engines("blueskies epically ophydia runengines_plural")


@pytest.mark.parametrize("term", sorted(ENGINE_TERMS))
def test_every_listed_engine_is_one_the_scanner_would_catch(term: str) -> None:
    """Guard the pattern build: a term the regex cannot express is unenforced."""
    assert find_engines(f"a line about {term} here") == [(1, f"a line about {term} here")]


def test_no_source_or_docs_file_names_a_particular_engine() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        for number, line in find_engines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")

    assert not offenders, (
        "Source or documentation names a particular engine:\n  "
        + "\n  ".join(offenders)
        + "\n\nWhich engine a deployment runs is a deployment's fact, so a rule "
        "stated for one reads as a rule derived from one. Say what holds for "
        "any engine, and keep what only one does in the adapter that speaks "
        "to it, or in spikes/ until that adapter exists."
    )


def test_every_listed_engine_is_a_plain_lowercase_word() -> None:
    """A term carrying punctuation would silently rewrite the alternation.

    The pattern joins the list with `|` inside a group, so a term holding a
    regex metacharacter would change what every other term matches rather
    than failing on its own.
    """
    malformed = sorted(term for term in ENGINE_TERMS if not term.isalpha() or not term.islower())
    assert malformed == [], f"ENGINE_TERMS entries must be plain lowercase words: {malformed}"
