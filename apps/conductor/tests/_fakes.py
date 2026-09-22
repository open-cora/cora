"""Seams that record what they were asked, so a walk can be checked.

Neither talks to anything. What a real control seam and a real
acquisition engine do to a beamline is measured in `spikes/conductor/`,
and nothing in this package's tests needs a beamline to check that a
procedure walked the way it was written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from conductor.seams import Acquired

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

    def acquire(self, plan: str, parameters: Mapping[str, object], reference: str) -> Acquired:
        if self.breaks_on is not None and plan == self.breaks_on:
            raise RuntimeError(f"the engine refused {plan}")
        self.asked.append((plan, parameters, reference))
        return Acquired(
            reference=reference,
            engine_reference=f"engine-uid-for-{reference}",
            said=self.says,
        )
