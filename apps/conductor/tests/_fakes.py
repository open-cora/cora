"""Seams that record what they were asked, so a walk can be checked.

Neither talks to anything. What a real control seam and a real
acquisition engine do to a beamline is measured in `spikes/conductor/`,
and nothing in this package's tests needs a beamline to check that a
procedure walked the way it was written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from conductor.seams import Acquired, BoundNotEnforceableError, Setting

Asked = tuple[str, Mapping[str, object], str, float | None]
"""One request an engine received: the plan, its parameters, the reference, the bound.

A runtime alias rather than an annotation, because the factory below
builds a parametrised list from it and a name only the type checker can
see would not be there when it ran.
"""


@dataclass(slots=True)
class RecordingControl:
    """Remembers every write, and can be told to break on one record.

    The two verbs are kept in separate lists rather than one, because a
    test that asserts a procedure moved a motor should fail if the motor
    was set instead. Merging them would let the wrong verb pass.
    """

    moves: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])
    sets: list[tuple[str, Setting]] = field(default_factory=list[tuple[str, Setting]])
    values: dict[str, Setting] = field(default_factory=dict[str, Setting])
    breaks_on: str | None = None

    def move(self, record: str, value: float) -> None:
        if self.breaks_on is not None and record == self.breaks_on:
            raise TimeoutError(f"{record} did not get there")
        self.moves.append((record, value))
        self.values[record] = value

    def set(self, record: str, value: Setting) -> None:
        if self.breaks_on is not None and record == self.breaks_on:
            raise TimeoutError(f"{record} would not take it")
        self.sets.append((record, value))
        self.values[record] = value

    def read(self, record: str) -> Setting:
        return self.values.get(record, 0.0)


@dataclass(slots=True)
class RecordingAcquisition:
    """Remembers every plan it was asked for, with the reference it carried."""

    asked: list[Asked] = field(default_factory=list[Asked])
    says: str = "success"
    breaks_on: str | None = None
    answers_with: str | None = None
    """A reference to return instead of the one given, for the adapter that drops it."""

    refuses_bounds: bool = False
    """Whether to behave like an engine that cannot be given up on.

    `BlueskyAcquisition` is one: a bare RunEngine runs a plan in the
    calling thread. A test wanting that refusal sets this rather than
    importing the adapter, which would put an adapter's name in a test
    of the core.
    """

    def acquire(
        self,
        plan: str,
        parameters: Mapping[str, object],
        reference: str,
        bound: float | None,
    ) -> Acquired:
        if bound is not None and self.refuses_bounds:
            raise BoundNotEnforceableError(plan=plan, bound=bound, because="this double says so")
        if self.breaks_on is not None and plan == self.breaks_on:
            raise RuntimeError(f"the engine refused {plan}")
        self.asked.append((plan, parameters, reference, bound))
        return Acquired(
            reference=self.answers_with if self.answers_with is not None else reference,
            engine_reference=f"engine-uid-for-{reference}",
            said=self.says,
        )
