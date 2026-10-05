"""The adapter table on the beamlines page, held to the registers it reports.

`beamlines/<name>/adapters.toml` says which adapter fills which seam there,
and `beamlines/tests/test_adapters.py` resolves every name in it against the
app that owns the slot. So a renamed module reddens a test rather than leaving
a register that lies.

Nothing extended that to prose. `docs/beamlines/index.md` carries a table of
the same slots, and that table is the thing a reader consults before deciding
what a beamline can do. It was written by hand from the registers and could
drift from them silently, which is the failure the register's own docstring
warns about in as many words: a hand-kept table of names rots, and prose that
lists things is not checked by anything.

## What this catches, and what it does not

It catches the two ways the table can go wrong. A slot whose adapter changes
in the register and not on the page, and a slot that leaves the register
without leaving the page. It also pins the sentence the table leans on, that
all four beamlines carry the same register, because the moment one diverges a
single table cannot describe them and the page has to say so.

It does not check the third column, which says what a seam is for. That is
prose about a design and is not derivable from a register, so it stays the
responsibility of whoever edits it.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, cast

import pytest

from tests._tracked import TREE_ROOT, tracked_adapter_files

if TYPE_CHECKING:
    from pathlib import Path

PAGE = TREE_ROOT / "docs" / "beamlines" / "index.md"

ROW = re.compile(r"^\|\s*`(\w+\.\w+)`\s*\|\s*`(\w+)`\s*\|", re.MULTILINE)
"""A table row naming a slot and the adapter in it, both in backticks.

Anchored on the dotted slot rather than on the heading above it, so moving
the table within the page or retitling its section leaves this working. A
row whose first two cells are not both code spans is not one of these rows
and is skipped, which is what lets the page carry other tables.

Word characters rather than letters alone, because an adapter is named for
the format it reads and those carry digits. Written with letters only, this
stopped seeing `dxchange_hdf5` on its first run, which the slot check caught
by reporting the row as missing from the page.
"""


def _register(path: Path) -> dict[str, str]:
    """One register flattened to `table.key` against the adapter named there.

    The cast rather than a shape check, for the reason the sibling register
    pin gives: a register that is not tables of strings is a broken register,
    and `beamlines/tests` is where that is caught. Failing loudly here beats
    reporting an empty one.
    """
    settings: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        f"{table}.{key}": value
        for table, entries in settings.items()
        if isinstance(entries, dict)
        for key, value in cast("dict[str, str]", entries).items()
    }


def _registers() -> dict[str, dict[str, str]]:
    return {path.parent.name: _register(path) for path in tracked_adapter_files()}


def _tabled() -> dict[str, str]:
    return dict(ROW.findall(PAGE.read_text(encoding="utf-8")))


def test_the_page_carries_an_adapter_table_at_all() -> None:
    assert _tabled(), (
        f"{PAGE.relative_to(TREE_ROOT)} has no rows naming a slot and an adapter, "
        f"so every check below passes while reporting nothing. The table's rows "
        f"have to open with the dotted slot and the adapter, each in backticks."
    )


def test_every_beamline_carries_the_same_adapter_register() -> None:
    registers = _registers()
    distinct = {tuple(sorted(register.items())) for register in registers.values()}
    assert len(distinct) == 1, (
        f"The beamlines no longer carry identical adapter registers, and "
        f"{PAGE.relative_to(TREE_ROOT)} says they do and prints one table for all "
        f"of them. Give the page a column or a row per beamline before changing "
        f"a register, or the table describes whichever one it was written from. "
        f"Registers now: { {name: register for name, register in sorted(registers.items())} }"
    )


@pytest.mark.parametrize("beamline", sorted(_registers()))
def test_every_slot_in_a_register_is_reported_by_the_page(beamline: str) -> None:
    register, tabled = _registers()[beamline], _tabled()
    missing = sorted(set(register) - set(tabled))
    assert not missing, (
        f"beamlines/{beamline}/adapters.toml holds {missing} and "
        f"{PAGE.relative_to(TREE_ROOT)} never names them, so the page reports "
        f"part of a register as though it were the whole of one. A reader "
        f"deciding what the beamline can do cannot see the slots left out."
    )


@pytest.mark.parametrize("beamline", sorted(_registers()))
def test_every_slot_the_page_reports_names_the_adapter_in_the_register(beamline: str) -> None:
    register, tabled = _registers()[beamline], _tabled()
    wrong = {
        slot: (adapter, register[slot])
        for slot, adapter in tabled.items()
        if slot in register and adapter != register[slot]
    }
    assert not wrong, (
        f"{PAGE.relative_to(TREE_ROOT)} and beamlines/{beamline}/adapters.toml "
        f"disagree about what fills these slots, as page against register: "
        f"{wrong}. The register is the one a test resolves against real modules, "
        f"so the page is what has to change."
    )


@pytest.mark.parametrize("beamline", sorted(_registers()))
def test_no_slot_on_the_page_is_absent_from_the_register(beamline: str) -> None:
    register, tabled = _registers()[beamline], _tabled()
    stale = sorted(set(tabled) - set(register))
    assert not stale, (
        f"{PAGE.relative_to(TREE_ROOT)} reports {stale}, which "
        f"beamlines/{beamline}/adapters.toml does not hold. A slot removed from "
        f"the registers has to leave the page with them, or the page goes on "
        f"describing a seam nothing fills."
    )
