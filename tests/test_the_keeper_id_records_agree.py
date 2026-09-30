"""One record name, spelled in three places that never meet.

`beamlines/keeper-ids/records.db` declares two records. The conductor writes
them before it starts a scan and the reporter reads them back when the scan
ends, and each names them with its own string constant in its own project.

Nothing else compares the three. Each project's suite enumerates its own
directory on purpose, per the mirror rule, so neither adapter's tests can see
the database and neither can see the other. A rename in one of them leaves
the other two alone, every lane stays green, and the failure appears at a
beamline as scans that carry no ids: the conductor writes a name nothing
serves, the write succeeds against a channel that never connects, and the
reporter reads a record that was never written and ignores the scan for
looking like one somebody ran by hand.

This is the only check that reads all three, which is why it lives here
rather than in either project.

## Why the names are read rather than imported

Importing the adapters would mean this tier installing both projects and
their Channel Access dependency, and the tier deliberately installs neither.
Reading the constant out of the source is enough, because what is being
compared is the literal string either way.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[1]

RECORDS_DB = TREE / "beamlines" / "keeper-ids" / "records.db"

ADAPTERS = (
    TREE / "apps" / "conductor" / "src" / "conductor" / "adapters" / "tomoscan_engine.py",
    TREE / "apps" / "reporter" / "src" / "reporter" / "adapters" / "tomoscan_records.py",
)

CONSTANTS = ("EXECUTION_ID", "STEP_ID")
"""The two module-level names each adapter holds a record name in.

Spelled the same in both by coincidence of them being written together
rather than by a rule, so a rename of the constant fails this and that is
correct: the test would otherwise range over nothing.
"""

EXPECTED_RECORDS = 2
"""How many records the database declares.

Pinned because every assertion below compares sets, and a database that
declared nothing would satisfy a comparison against two adapters that
also somehow declared nothing. Raise it only after adding a record that
both adapters name.
"""

_RECORD = re.compile(r'record\s*\(\s*\w+\s*,\s*"\$\(P\)\$\(R\)(?P<name>\w+)"\s*\)')


def _declared_records() -> set[str]:
    """The record names in the database, with the macro prefix removed.

    The prefix is part of the pattern rather than stripped afterwards, so a
    record written without it fails to match and shows up as missing. That
    is the right answer: a record not under $(P)$(R) is at a different
    address from the rest and no adapter would find it.
    """
    text = RECORDS_DB.read_text(encoding="utf-8")
    return {match.group("name") for match in _RECORD.finditer(text)}


def _named_by(adapter: Path) -> set[str]:
    """The record names an adapter holds in the constants above."""
    tree = ast.parse(adapter.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.AnnAssign(
                target=ast.Name(id=name), value=ast.Constant(value=str() as record)
            ) if name in CONSTANTS:
                found.add(record)
            case ast.Assign(
                targets=[ast.Name(id=name)], value=ast.Constant(value=str() as record)
            ) if name in CONSTANTS:
                found.add(record)
            case _:
                continue
    return found


def test_the_database_declares_the_records_it_is_read_for() -> None:
    """Guard the enumeration, so the comparisons below cannot pass vacuously."""
    declared = _declared_records()
    assert len(declared) == EXPECTED_RECORDS, (
        f"beamlines/keeper-ids/records.db declares {sorted(declared)}. A database "
        "this test found nothing in would agree with anything."
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda p: f"{p.parents[1].name}/{p.name}")
def test_an_adapter_names_a_record_the_database_declares(adapter: Path) -> None:
    named = _named_by(adapter)
    assert len(named) == EXPECTED_RECORDS, (
        f"{adapter.name} holds {sorted(named)} in {list(CONSTANTS)}. Renaming a "
        "constant makes this test range over nothing, which is why it is counted "
        "rather than merely compared."
    )
    missing = sorted(named - _declared_records())
    assert not missing, (
        f"{adapter.name} reads {missing}, which beamlines/keeper-ids/records.db "
        "does not declare. A conductor writing a record nothing serves succeeds "
        "against a channel that never connects, and the scan is filed against "
        "nothing."
    )


def test_both_adapters_name_the_same_records() -> None:
    """The conductor writes what the reporter reads, or the join is broken.

    Separate from the checks above because two adapters could each name a
    record the database declares and still name different ones, which is
    the same beamline failure with every individual comparison passing.
    """
    conductor, reporter = (_named_by(adapter) for adapter in ADAPTERS)
    assert conductor == reporter, (
        f"the conductor writes {sorted(conductor)} and the reporter reads "
        f"{sorted(reporter)}. Nothing joins a finished scan to its step unless "
        "these are the same two records."
    )
