"""Seams that keep what they were asked, so a walk can be checked.

None of them talks to anything. What a real control seam and a real
acquisition engine do to a beamline is measured in a spike,
and nothing in this package's tests needs a beamline to check that a
procedure walked the way it was written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from conductor.seams import Acquired, Citation

if TYPE_CHECKING:
    from conductor.outcomes import Outcome
    from conductor.seams import Assignment

Asked = tuple[str, Mapping[str, object], "Citation | None"]
"""One request an engine received: the plan, its parameters, the keeper's ids.

A runtime alias rather than an annotation, because the factory below
builds a parametrised list from it and a name only the type checker can
see would not be there when it ran.
"""


@dataclass(slots=True)
class RecordingControl:
    """Remembers every move, and can be told to break on one of them."""

    moves: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])
    positions: dict[str, float] = field(default_factory=dict[str, float])
    breaks_on: str | None = None

    def move(self, record: str, value: float) -> None:
        if self.breaks_on is not None and record == self.breaks_on:
            raise TimeoutError(f"{record} did not get there")
        self.moves.append((record, value))
        self.positions[record] = value

    def read(self, record: str) -> float:
        return self.positions.get(record, 0.0)


@dataclass(slots=True)
class RecordingAcquisition:
    """Remembers every plan it was asked for, with the ids it carried."""

    asked: list[Asked] = field(default_factory=list[Asked])
    says: str = "success"
    breaks_on: str | None = None
    answers_with: Citation | None = None
    """A citation to return instead of the one given, for the engine that drops them."""

    def acquire(
        self, plan: str, parameters: Mapping[str, object], cites: Citation | None
    ) -> Acquired:
        if self.breaks_on is not None and plan == self.breaks_on:
            raise RuntimeError(f"the engine refused {plan}")
        self.asked.append((plan, parameters, cites))
        return Acquired(
            cites=self.answers_with if self.answers_with is not None else cites,
            engine_reference=f"engine-uid-for-{plan}",
            said=self.says,
        )


class RecordingRefusedError(RuntimeError):
    """The reporting seam would not take a report."""


Stepped = tuple[int, "Outcome"]
"""One step report: the step's index, and how it ended.

Two values where it was three. The walk's reference went with
`walk_began`: a `Reporting` is bound to one execution before `conduct`
is given it, so nothing below that binding names a record.
"""


@dataclass(slots=True)
class CollectingRecording:
    """Keeps every report a walk made, and can refuse one of them.

    `order` holds nothing but method names, which is what the ordering
    checks read. `stepped` holds the arguments, so a test asserting
    content does not have to pick it out of a heterogeneous sequence.
    """

    stepped: list[Stepped] = field(default_factory=list[Stepped])
    ended: int = 0
    order: list[str] = field(default_factory=list[str])
    refuses_step: int | None = None
    """A step index whose report raises, for the walk nothing can be told about."""

    def step_ended(self, index: int, outcome: Outcome) -> None:
        if self.refuses_step is not None and index == self.refuses_step:
            raise RecordingRefusedError(f"nothing could be told about step {index}")
        self.order.append("step_ended")
        self.stepped.append((index, outcome))

    def walk_ended(self) -> None:
        self.order.append("walk_ended")
        self.ended += 1


Reported = tuple[str, int, "Outcome"]
"""One step report as the whole seam sees it: the execution, the index, the outcome.

Three values where `Stepped` has two, because `Keeper` is not bound to an
execution and `Reporting` is. Which of the two a test uses says which
layer it is checking.
"""


@dataclass(slots=True)
class CollectingKeeper:
    """An the keeper that hands out prepared work and keeps everything it is told.

    `waiting` is answered in order and then exhausted, so a loop given two
    assignments and left running finds nothing on every turn after the
    second. That is what an idle beamline looks like and is the state a
    conductor spends almost all of its time in.

    `grants_claims` is the race, not a fault. A conductor that loses one
    is the ordinary outcome of two seeing one dispatch.
    """

    waiting: list[Assignment] = field(default_factory=list["Assignment"])
    grants_claims: bool = True
    refuses_take: BaseException | None = None
    refuses_report: BaseException | None = None
    asked: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])
    claimed: list[str] = field(default_factory=list[str])
    reported: list[Reported] = field(default_factory=list[Reported])
    finished: list[str] = field(default_factory=list[str])

    def take(self, beamline: str, wait: float) -> Assignment | None:
        self.asked.append((beamline, wait))
        if self.refuses_take is not None:
            raise self.refuses_take
        return self.waiting.pop(0) if self.waiting else None

    def claim(self, execution_id: str) -> bool:
        self.claimed.append(execution_id)
        return self.grants_claims

    def report(self, execution_id: str, index: int, outcome: Outcome) -> None:
        if self.refuses_report is not None:
            raise self.refuses_report
        self.reported.append((execution_id, index, outcome))

    def finish(self, execution_id: str) -> None:
        self.finished.append(execution_id)
