"""A service whose log never arrives is a service nobody can watch.

Python buffers stdout when it is not a terminal. A unit that prints a
line a minute therefore fills a block buffer it will not flush for
hours, or ever, and in the meantime its log reads as empty.

That is not a cosmetic problem here, because what these units print is
the only evidence some of them produce. Measured on a beamline host: the
watcher started, printed what it was accounting for, and the journal
held nothing but systemd's own `Started` line. Its installer checks for
that sentence before calling the install good, and refused, correctly,
an install of a service that was running perfectly.

The unit's own comment told a reader to follow it with
`journalctl --user -u cora-watcher -f`, which would have shown them
nothing for as long as they were willing to sit there.

## Why every unit and not just the ones that noticed

Not one unit template in this tree set it. The two that write to a file
instead of the journal have the same buffer between them and the file,
so the difference was only in where the silence was. A rule that covered
the watcher alone would leave eight others to be found one at a time, by
somebody trying to read a log during an incident.

## Why the environment variable rather than `-u`

Both work. The variable survives an ExecStart that is edited or wrapped,
and three of these are not a bare `python3` call: one runs uvicorn and
two substitute an interpreter in at install time.
"""

from __future__ import annotations

import re
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

RUNS_PYTHON = re.compile(r"^ExecStart=.*(python|uvicorn|@PYTHON@)", re.M | re.I)
"""An ExecStart that starts an interpreter, however it names one."""

MINIMUM = 8
"""How many such units are expected.

Pinned so that a rule matching nothing passes loudly rather than
quietly. A layout change that moved the templates would otherwise leave
this scanning an empty list and reporting success.
"""


def _units() -> list[Path]:
    return sorted(TREE.glob("apps/*/infra/*/*.service.in"))


def _python_units() -> list[Path]:
    return [path for path in _units() if RUNS_PYTHON.search(path.read_text(encoding="utf-8"))]


def test_the_units_this_rule_reads_are_still_there() -> None:
    found = _python_units()

    assert len(found) >= MINIMUM, (
        f"{len(found)} unit templates start an interpreter and at least "
        f"{MINIMUM} were expected. Confirm the layout changed on purpose, "
        "then move the number in the same commit."
    )


def _unbuffered(text: str) -> bool:
    """Either way of saying it, because both work and both are in use."""
    if "PYTHONUNBUFFERED=1" in text:
        return True
    started = RUNS_PYTHON.search(text)
    return started is not None and " -u " in started.group(0)


def test_every_unit_that_starts_an_interpreter_unbuffers_its_output() -> None:
    buffered = [
        str(path.relative_to(TREE))
        for path in _python_units()
        if not _unbuffered(path.read_text(encoding="utf-8"))
    ]

    assert not buffered, (
        f"{buffered} start an interpreter without unbuffering it. Python "
        "block-buffers stdout when it is not a terminal, so whatever they "
        "print sits unflushed and the log reads as empty while the service "
        "runs perfectly. One installer in this tree checks a log line "
        "before calling an install good, and this is what made it refuse."
    )
