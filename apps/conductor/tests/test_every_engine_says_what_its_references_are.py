"""Each engine this ships says whether its references are addresses or names.

The distinction decides who records where a run's data went, and it is
the whole reason `conductor.seams.Filing` exists on a driver at all.

An engine answering with a location has already given the address, so
the conductor holding it can file it and nothing else has to be asked.
An engine answering with a name has said only what the run was called,
and turning that into an address needs the store, so a reporter beside
the store does it. Getting this backwards at either end produces a
catalogue entry that resolves to nothing, or none at all.

Typing already refuses an engine that declares no scheme, because
`engine_for` returns a `Running` and the Protocol carries the property.
What typing cannot see is the value being wrong, which is what this
reads. The list is written out rather than discovered, so a third
engine is a line here and a decision made on purpose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conductor.__main__ import NoEngine
from conductor.adapters.bluesky_engine import BlueskyEngine
from conductor.adapters.tomoscan_engine import POSIX_FILE, TomoscanEngine

if TYPE_CHECKING:
    from conductor.seams import Running

ENGINES: tuple[type[Running], ...] = (BlueskyEngine, NoEngine, TomoscanEngine)
"""Every implementation of the engine seam this package ships.

Three, and the third is the refusal an entrypoint substitutes when a
deployment named no engine. It is here because it is a `Running` like
the others and would otherwise be the one that could drift.
"""

EXPECTED_ENGINES = 3


def test_the_engines_this_ranges_over_are_still_the_ones_that_ship() -> None:
    """Guard the list, because a rule ranging over nothing passes."""
    assert len(ENGINES) == EXPECTED_ENGINES


def test_every_engine_declares_what_kind_of_reference_it_gives() -> None:
    missing = [engine.__name__ for engine in ENGINES if not hasattr(engine, "reference_scheme")]
    assert missing == [], (
        f"{missing} implement the engine seam and say nothing about their "
        "references, so a conductor cannot tell whether to file one"
    )


def test_a_tomoscan_reference_is_an_address_and_needs_resolving_by_nobody() -> None:
    """It is the path of the file the server just wrote.

    Against the spelling rather than against `POSIX_FILE`, which would
    compare the constant with itself and pass on any value at all. The
    word is an agreement with whatever resolves a dataset later, the
    same way the two metadata keys are pinned to literals on each side,
    so the literal is the thing worth holding still.
    """
    assert TomoscanEngine.reference_scheme == "posix-file"
    assert POSIX_FILE == "posix-file"


def test_a_bluesky_reference_is_a_name_that_only_a_store_can_resolve() -> None:
    """A run uid says what the run was called and nothing about where data went."""
    assert BlueskyEngine.reference_scheme is None


def test_an_engine_that_runs_nothing_gives_no_reference_to_file() -> None:
    assert NoEngine.reference_scheme is None
