"""Installing a unit for the first time must not abort on its empty journal.

Every installer in this tree runs under `set -euo pipefail` and reads a
journal cursor before starting the service, so that the checks after the
start read only what this install produced rather than last week's.

A unit being installed for the first time has no journal. `journalctl`
exits non-zero saying so, the pipeline fails, and the assignment takes
the whole script down with it. Measured on a beamline host: the unit
file was written, the script exited 1 having printed only the word
`Unit`, and the service was left present, disabled and dead.

## Why this went unnoticed

The second install of the same unit works, because by then the journal
has the first attempt in it. So every installer in this tree passed its
own trial runs and failed on exactly the occasion that matters, which is
the one time an operator is watching a service appear.

## What is compared

Each installer's cursor read, which must tolerate a failure. An empty
cursor is already handled downstream as "read the whole journal", and
for a unit that has none that is this install's own output, which is
what was wanted anyway.

A test rather than a comment because the two installers are in two
projects that cannot import each other, each carries its own copy of
this pattern, and a third project adding an installer would copy
whichever it found.
"""

from __future__ import annotations

import re
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

CURSOR = re.compile(r"\$\(\s*journalctl[^)]*--show-cursor[^)]*\)", re.S)
"""A command substitution that reads a journal cursor."""

MINIMUM = 2
"""How many installers are expected to read one.

Pinned so that a rule finding nothing to check fails loudly. A rename
that stopped this matching any file would otherwise pass in silence,
which is the failure this whole tier has met before.
"""


def _installers() -> list[Path]:
    return sorted(TREE.glob("apps/*/infra/*/install*.sh"))


def test_the_installers_this_rule_reads_are_still_there() -> None:
    found = [path for path in _installers() if CURSOR.search(path.read_text(encoding="utf-8"))]

    assert len(found) >= MINIMUM, (
        f"{len(found)} installers read a journal cursor and at least {MINIMUM} "
        "were expected. If one stopped, confirm it on purpose and move the "
        "number in the same commit."
    )


def test_every_installer_tolerates_a_unit_that_has_no_journal_yet() -> None:
    unguarded: list[str] = []
    for path in _installers():
        for found in CURSOR.finditer(path.read_text(encoding="utf-8")):
            if "|| true" not in found.group(0):
                unguarded.append(str(path.relative_to(TREE)))

    assert not unguarded, (
        f"{unguarded} read a journal cursor without tolerating a failure. "
        "A unit installed for the first time has no journal, journalctl "
        "exits non-zero, and under set -euo pipefail the assignment ends "
        "the script after the unit file is written and before it is "
        "started. The unit is left present, disabled and dead, and the "
        "second install of the same unit works, so this does not show up "
        "in a trial run."
    )
