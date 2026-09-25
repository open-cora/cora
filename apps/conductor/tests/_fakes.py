"""Seams that keep what they were asked, so a walk can be checked.

None of them talks to anything. What a real control seam and a real
acquisition engine do to a beamline is measured in `spikes/conductor/`,
and nothing in this package's tests needs a beamline to check that a
procedure walked the way it was written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from conductor.seams import Acquired

if TYPE_CHECKING:
    from conductor.outcomes import Outcome

Asked = tuple[str, Mapping[str, object], str]
"""One request an engine received: the plan, its parameters, the reference.

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
    """Remembers every plan it was asked for, with the reference it carried."""

    asked: list[Asked] = field(default_factory=list[Asked])
    says: str = "success"
    breaks_on: str | None = None
    answers_with: str | None = None
    """A reference to return instead of the one given, for the adapter that drops it."""

    def acquire(self, plan: str, parameters: Mapping[str, object], reference: str) -> Acquired:
        if self.breaks_on is not None and plan == self.breaks_on:
            raise RuntimeError(f"the engine refused {plan}")
        self.asked.append((plan, parameters, reference))
        return Acquired(
            reference=self.answers_with if self.answers_with is not None else reference,
            engine_reference=f"engine-uid-for-{reference}",
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
