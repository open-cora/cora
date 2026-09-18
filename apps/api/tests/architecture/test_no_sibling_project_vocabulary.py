"""Source may not name the sibling project or carry its domain vocabulary.

This repository's chassis was copied once from a sibling project and is owned
outright from that point on. Two consequences are written down elsewhere and
neither had a check behind it:

  - CLAUDE.md: no provenance comments pointing at the sibling tree.
  - README.md: the sibling's facility vocabulary "appears nowhere in this
    tree".

Both were untrue when this file was written. Source named the sibling twice,
to say what its kernel carries and what it names its tracer, and its
aggregates turned up in five more docstrings explaining a knob by naming the
slices that used it over there. Prose naming code that does not exist costs a
reader a search that ends in nothing, which is the same defect
`test_docstring_references_resolve.py` next door was built for.

## Why this is a separate rule from that one

That rule resolves a name against the tree, which requires the name to look
like a name: backticked, and shaped like an identifier. Half of what came
across was neither. `Equipment's Asset + Family is the first case` is ordinary
prose with ordinary capitals, and no resolution rule reaches it without
flagging every sentence that starts with a word. A closed list of the
sibling's nouns does reach it, at the cost of only catching what is listed.

So read the two together: the rule next door is general and shape-bound, this
one is shape-blind and specific. Neither subsumes the other.

## What is deliberately NOT in the list

Three of the six nouns README names are ordinary English in a codebase like
this one, and banning them would fail on prose that has nothing to do with the
sibling:

  - `capture`, as in what a log handler does to a stream.
  - `supply`, as in what a handler does with a timestamp.
  - `allocation`, as in memory or a connection pool.

A word this common cannot be told from its domain use by a scan, so those
three are left to review. The list holds only nouns with no other meaning
here, which is what makes a hit worth acting on rather than worth excepting.
"""

import re
from pathlib import Path

import pytest

from tests.architecture.conftest import REPO_ROOT, tracked_python_files, tracked_test_files

pytestmark = pytest.mark.architecture

SIBLING_PROJECT_TERMS: frozenset[str] = frozenset(
    {
        # The project itself, which CLAUDE.md bans source from pointing at.
        # Both mentions that were here explained this tree by describing that
        # one, which is the habit the ban exists to stop.
        "cora",
        # The sibling's facility vocabulary, as README enumerates it, less the
        # three ordinary words named in the module docstring.
        "beam",
        "clearance",
        "enclosure",
        # Aggregates found in chassis docstrings during the sweep that added
        # this file. Each explained a parameter by naming a slice over there.
        "equipment",
        "procedure",
        "recipe",
    }
)
"""Words that name the sibling project or something only it models.

An entry earns its place by having no other meaning in this codebase, so a
hit is a defect rather than a candidate for an exception. Removing one is the
right move only if this project comes to model the thing itself, and that is
a decision worth making on purpose.
"""

_TERM_PATTERN = re.compile(rf"\b(?:{'|'.join(sorted(SIBLING_PROJECT_TERMS))})s?\b", re.IGNORECASE)

_THIS_FILE = "test_no_sibling_project_vocabulary.py"


def find_terms(text: str) -> list[tuple[int, str]]:
    """Every line of `text` carrying a listed term, as (line number, line).

    Takes the text rather than a path so the check below can be run against
    input of the caller's choosing, which is the only way to show it fires.
    """
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if _TERM_PATTERN.search(line)
    ]


def _scanned_files() -> list[Path]:
    """Tracked source and test files, minus this one.

    This file has to name what it refuses, so scanning it would fail on its
    own list.
    """
    return sorted(
        path for path in tracked_python_files() | tracked_test_files() if path.name != _THIS_FILE
    )


def test_the_vocabulary_scan_covers_the_tree() -> None:
    """Guard the enumeration: an empty file set makes the rule below vacuous."""
    assert _scanned_files(), "No tracked source file found, so the scan below reads nothing."


def test_the_scanner_finds_a_term_and_leaves_ordinary_prose_alone() -> None:
    """Run the scanner over text of this test's choosing, since the tree is clean.

    The second half matters as much as the first. A scanner keyed on
    substrings rather than words would hit `beamline` and `procedural`, and a
    rule that fires on ordinary prose gets excepted into uselessness.
    """
    hits = find_terms("a docstring naming Equipment's Asset\nand a clean line\n")
    assert hits == [(1, "a docstring naming Equipment's Asset")]

    assert find_terms("CORA names its tracer after the first BC")
    assert find_terms("the four clearances a request needs")

    assert not find_terms("corallary beamline procedural recipes_are_not_here")


@pytest.mark.parametrize("term", sorted(SIBLING_PROJECT_TERMS))
def test_every_listed_term_is_one_the_scanner_would_catch(term: str) -> None:
    """Guard the pattern build: a term the regex cannot express is not enforced."""
    assert find_terms(f"a line about {term} here") == [(1, f"a line about {term} here")]


def test_no_source_file_names_the_sibling_project_or_its_vocabulary() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        for number, line in find_terms(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line}")

    assert not offenders, (
        "Source names the sibling project or something only it models:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe chassis is owned outright here, so prose explaining it should "
        "describe this tree rather than the one it was copied from. If this "
        "project has genuinely come to model the thing, drop the word from "
        "SIBLING_PROJECT_TERMS in the same commit and say so."
    )


def test_every_listed_term_is_a_plain_lowercase_word() -> None:
    """A term carrying punctuation would silently rewrite the alternation.

    The pattern joins the list with `|` inside a group, so a term containing
    a regex metacharacter would change what every other term matches rather
    than just failing on its own.
    """
    malformed = sorted(
        term for term in SIBLING_PROJECT_TERMS if not term.isalpha() or not term.islower()
    )
    assert malformed == [], (
        f"SIBLING_PROJECT_TERMS entries must be plain lowercase words: {malformed}"
    )
