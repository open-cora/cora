"""The name a handed-off scan is given, spelled out in two projects.

A transfer or a reconstruction is handed to a service that mints an id,
and the id is the reference. TomoScan mints nothing: it is a state
machine published as records, holding the scan it is running now. So the
reference for a scan is built out of what identifies one, and the format
is an agreement between the program that writes it and the program that
reads it.

`apps/conductor/src/conductor/adapters/tomoscan_engine.py` builds it,
when a scan is still running at the end of the walk's bound.

`apps/reporter/src/reporter/adapters/tomoscan_scans.py` takes it apart,
when the watcher comes round to ask how that scan went.

Neither can import the other. They ship as separate repositories and
will not be installed beside each other, which is the rule the whole
tree is arranged around, so each spells the format out. This is the only
thing that reads both.

## Why drift here is quiet in the worst way

Nothing raises. A reader that does not recognise the writer's format
treats the reference as a stranger's, which is exactly what it is
supposed to do with a Globus task id, so the watcher logs it and leaves
it. The step then stays handed off for good.

That reads as a scan still running, which for a scan that really is
running is the correct display. So the symptom of this breaking is a
beamline that appears to have a scan in progress, forever, and an
operator with no reason to doubt it.

The record names matter for the same reason and are compared too. A
reader looking at the wrong records finds nothing and reports nothing,
which is the same silence.
"""

from __future__ import annotations

import ast
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

WRITING = TREE / "apps" / "conductor" / "src" / "conductor" / "adapters" / "tomoscan_engine.py"
READING = TREE / "apps" / "reporter" / "src" / "reporter" / "adapters" / "tomoscan_scans.py"

SHARED = ("REFERENCE_SCHEME", "REFERENCE_SEPARATOR", "EXECUTION_ID", "STEP_ID", "START_SCAN")
"""Every literal the two have to say the same way.

The first two are the format itself. The last three are where the
reader looks, which the writer decides by writing the ids into those
records before it starts the scan.
"""

IDLE = "IDLE_VALUE"
"""What both call the value that means a scan is over.

Separate from the list above only because the writer waits for it and
the reader tests for it, so the two reach it by different routes and
could drift without either looking wrong on its own.
"""


def _literals(module: Path) -> dict[str, str]:
    """Every module-level `NAME: Final = "text"` in one file."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        value = node.value
        if not names or not isinstance(value, ast.Constant):
            continue
        if isinstance(value.value, str):
            found[names[0]] = value.value
    return found


def test_both_projects_still_declare_what_this_rule_compares() -> None:
    """The guard, so that comparing two empty sets cannot pass quietly."""
    for module in (WRITING, READING):
        declared = _literals(module)
        missing = [name for name in (*SHARED, IDLE) if name not in declared]
        assert not missing, (
            f"{module.relative_to(TREE)} no longer declares {missing}, so the "
            "comparison below would pass over the part that went."
        )


def test_the_writer_and_the_reader_agree_on_how_a_scan_is_named() -> None:
    writing, reading = _literals(WRITING), _literals(READING)
    differing = {
        name: (writing.get(name), reading.get(name))
        for name in (*SHARED, IDLE)
        if writing.get(name) != reading.get(name)
    }

    assert not differing, (
        "The engine that hands a scan over and the watcher that finishes its "
        f"record disagree about {sorted(differing)}: {differing}. Neither can "
        "import the other, so both spell it out and this is the only thing "
        "that reads both. A reader that does not recognise the writer's "
        "reference leaves the step handed off for good, which displays as a "
        "scan still running and gives nobody a reason to doubt it."
    )
