"""The faults a transfer never recovers from, spelled out in two projects.

Globus Transfer retries everything until a task's deadline, a day after
it was asked for, and it retries a missing file as patiently as a busy
endpoint. A missing file never arrives, so something has to decide which
faults are worth waiting through. Both programs that touch a transfer
make that decision, and they have to make it the same way.

`apps/conductor/infra/transferring/transfers.py` decides it while the
work is being driven: the engine reports a hopeless fault as a refusal
instead of waiting out its bound and handing off.

`apps/reporter/src/reporter/adapters/globus_transfer_tasks.py` decides
it afterwards, for work that was handed off and is still running: the
watcher reports a hopeless fault as a failure instead of polling it for
the rest of the day.

Neither can import the other. They ship as separate repositories and
will not be installed beside each other, which is the rule the whole
tree is arranged around, so each spells the set out. Nothing else reads
both: each project's suite enumerates its own directory, so the
conductor's tests cannot see the reporter's adapter and the reporter's
cannot see the engine. This is the only check that reads both, which is
why it lives here.

## Why drift here is quiet

Nothing raises. A fault in one set and not the other means the two
programs disagree about one kind of failure, and the disagreement reads
as ordinary behaviour from either side.

The sharper direction is the watcher falling behind. A fault the engine
refuses and the watcher does not is one where a procedure stops and the
record of some earlier handoff is never completed, so an operator sees a
beamline that stopped for a reason, and separately a step that has been
running for a week. Nothing connects the two.

The other direction is milder and still wrong: a fault the watcher calls
fatal and the engine does not is a walk that waits out its whole bound
before handing off work that was never going to finish.

## Why the words are read rather than imported

Importing would mean this tier installing both projects, and the tier
deliberately installs neither. What is being compared is a set of string
literals either way.
"""

from __future__ import annotations

import ast
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

DRIVING = TREE / "apps" / "conductor" / "infra" / "transferring" / "transfers.py"
WATCHING = TREE / "apps" / "reporter" / "src" / "reporter" / "adapters" / "globus_transfer_tasks.py"

NAME = "HOPELESS"
"""What both of them call it, which is itself part of the agreement."""

EXPECTED = 8
"""How many faults the set holds.

Pinned so that a rule comparing two empty sets passes loudly rather than
quietly. Both sides shrinking to nothing together is exactly the shape
of breakage this file cannot otherwise see.
"""


def _declared_set(module: Path) -> frozenset[str]:
    """The string members of a module-level `NAME = frozenset({...})`."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if not any(isinstance(t, ast.Name) and t.id == NAME for t in targets):
            continue
        return frozenset(
            element.value
            for call in ast.walk(node)
            if isinstance(call, ast.Set)
            for element in call.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    raise AssertionError(f"{module.relative_to(TREE)} no longer declares {NAME}")


def test_both_projects_still_declare_the_set_this_rule_compares() -> None:
    """The guard on the comparison below, which is the point of the file."""
    for module in (DRIVING, WATCHING):
        found = _declared_set(module)
        assert len(found) == EXPECTED, (
            f"{module.relative_to(TREE)} declares {len(found)} faults and this rule "
            f"expects {EXPECTED}. Confirm both sides changed together, then move the "
            "number in the same commit."
        )


def test_the_driver_and_the_watcher_refuse_the_same_transfer_faults() -> None:
    driving, watching = _declared_set(DRIVING), _declared_set(WATCHING)

    assert driving == watching, (
        "The engine that drives a transfer and the watcher that finishes its "
        "record disagree about which faults are hopeless. "
        f"Only the driver refuses {sorted(driving - watching)}; "
        f"only the watcher refuses {sorted(watching - driving)}. "
        "Neither can import the other, so both spell the set out and this is "
        "the only thing that reads both."
    )
