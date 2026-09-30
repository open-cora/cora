"""A beamline page and the register it describes, held to one number.

`beamlines/<name>/devices.toml` is the register, and `docs/beamlines/<name>.md`
is the page somebody reads before going to that beamline. Nothing compared
them. `beamlines/tests/test_descriptor.py` pins each register's size against
the register itself, and this tier's prose rules check links, spelling and
markers, so a register can grow while its page goes on describing the old one
with every lane green.

That is not hypothetical. 19-BM's register went from one row to sixteen. Its
page kept saying one, kept explaining at length why one was all that existed,
and kept listing that beamline's slits and filters as deliberately unregistered
while six of them sat in the register. Three further pages carried the old
count in passing. The register's own pin was green throughout, because it
compares the register with a number beside it and never with the prose.

## What this catches, and what it does not

It catches a page whose stated size is not its register's, which is how this
drifts: the register is edited and the prose is not. It does not catch a page
that states the right number and is wrong about everything else, and it cannot,
because the rest of a page is prose about a facility rather than anything
derivable from the register.

The number has to qualify a noun. Without that, "one" in its ordinary English
sense would satisfy a one-row register from any sentence on the page, and the
check would be weakest exactly where these registers start.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, cast

import pytest

from tests._tracked import TREE_ROOT, tracked_register_files

if TYPE_CHECKING:
    from pathlib import Path

PAGES = TREE_ROOT / "docs" / "beamlines"

COUNTED_NOUNS = ("devices", "device", "rows", "row", "motors", "motor")
"""What a count may be counting.

Three words for one thing because the pages use all three and the difference
is editorial, not semantic: a register holds rows, the rows are devices, and
at a beamline whose devices are all motors a page says motors.
"""

NUMBER_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)
"""Spellings a page may use, indexed by the value. Digits are accepted too.

The table stops where prose does. A register larger than this is a listing
rather than a number somebody writes out, and a page describing one can say
so in digits; the failure message says as much, so the limit arrives as an
instruction rather than as a puzzle.
"""


def _registers() -> dict[str, Path]:
    """Every tracked register, by the beamline directory holding it."""
    return {path.parent.name: path for path in tracked_register_files()}


def _device_count(register: Path) -> int:
    """How many rows a register holds.

    The cast rather than a shape check because a register that is not a
    list of rows is a broken register, and `beamlines/tests` is where that
    is caught. Failing loudly here on one is better than reporting zero.
    """
    settings: dict[str, object] = tomllib.loads(register.read_text(encoding="utf-8"))
    return len(cast("list[object]", settings.get("device", [])))


def _spellings(count: int) -> tuple[str, ...]:
    if count < len(NUMBER_WORDS):
        return (str(count), NUMBER_WORDS[count])
    return (str(count),)


def _stated(page: str, count: int) -> bool:
    numbers = "|".join(_spellings(count))
    nouns = "|".join(COUNTED_NOUNS)
    return re.search(rf"\b({numbers})\s+({nouns})\b", page, re.IGNORECASE) is not None


@pytest.mark.parametrize("beamline", sorted(_registers()))
def test_every_register_in_the_directory_has_a_page(beamline: str) -> None:
    assert (PAGES / f"{beamline}.md").is_file(), (
        f"beamlines/{beamline}/devices.toml describes a beamline with no page at "
        f"docs/beamlines/{beamline}.md, so the check below reads nothing for it."
    )


@pytest.mark.parametrize("beamline", sorted(_registers()))
def test_every_beamline_page_states_the_size_of_its_register(beamline: str) -> None:
    count = _device_count(_registers()[beamline])
    page = (PAGES / f"{beamline}.md").read_text(encoding="utf-8")
    assert _stated(page, count), (
        f"beamlines/{beamline}/devices.toml holds {count} rows and "
        f"docs/beamlines/{beamline}.md never says so. The page has to state the "
        f"size where it describes the register, as one of {_spellings(count)} "
        f"followed by one of {COUNTED_NOUNS}. A page that keeps the old number "
        f"goes on explaining a register that is no longer there, which is what "
        f"happened at 19-BM."
    )
