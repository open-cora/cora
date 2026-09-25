"""A walk in its own process, journalling to a file, waiting to be killed.

Run as a script rather than imported, because what the test next door
measures is what a SIGKILL leaves behind, and a signal that took a
pytest process with it would leave nobody to look. It imports
`conductor` and the standard library only, so it needs nothing on the
path that installing the package does not already put there.

The journal is one JSON object per line, flushed on every write. Flushed
because the buffer is the thing under test: a report that reached only
Python's buffer is a report that dies with the process, which is the
defect the recording seam exists to close.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from conductor import Move, Procedure, conduct

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conductor.outcomes import Outcome
    from conductor.seams import Acquired, Citation

BLOCKS_ON = "2bmb:m3"
"""The record the third step moves, and the one nothing ever returns from."""

STEPS = 5
"""How many steps the procedure has, so the test can assert the two it lost."""


class JournalRecording:
    """Appends one line per report and flushes it before returning.

    Two methods, where the seam this stands in for had three. A walk no
    longer announces itself: the keeper writes the execution and its whole
    step list at dispatch, before anything is asked to drive it, so
    there is nothing for the first report to say that the record does
    not already hold.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def _append(self, entry: dict[str, object]) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
            handle.flush()

    def step_ended(self, index: int, outcome: Outcome) -> None:
        self._append(
            {
                "report": "step_ended",
                "index": index,
                "outcome": type(outcome).__name__,
            }
        )

    def walk_ended(self) -> None:
        self._append({"report": "walk_ended"})


class BlockingControl:
    """Moves everything at once, except the one record it never leaves."""

    def move(self, record: str, value: float) -> None:
        while record == BLOCKS_ON:
            time.sleep(0.05)

    def read(self, record: str) -> float:
        return 0.0


class UnusedAcquisition:
    """The procedure below has no acquisition step, and this proves it."""

    def acquire(
        self, plan: str, parameters: Mapping[str, object], cites: Citation | None
    ) -> Acquired:
        raise AssertionError("the procedure walked here has no acquisition step")


def main() -> None:
    journal = Path(sys.argv[1])
    records = ["2bmb:m1", "2bmb:m2", BLOCKS_ON, "2bmb:m4", "2bmb:m5"]
    procedure = Procedure(
        name="walk_until_killed",
        steps=tuple(Move(record=record, to=1.0) for record in records),
    )
    assert len(procedure.steps) == STEPS
    conduct(
        procedure,
        control=BlockingControl(),
        acquisition=UnusedAcquisition(),
        reporting=JournalRecording(journal),
    )


if __name__ == "__main__":
    main()
