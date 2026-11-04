"""The pass over every pursuit, and what it does when one of them refuses.

`turn_once` is covered next door against the same kind of double. What is
here is only what the entrypoint adds: that every pursuit is attempted,
and that one refusing does not cost the others their turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from conductor.config import ConfigError, turner_from_mapping
from conductor.turner import turn_every
from conductor.turning import Closed, Pursuit, Round


@dataclass
class _Record:
    """A record that answers for several pursuits and can refuse some."""

    running: tuple[Pursuit, ...] = ()
    refuses: frozenset[str] = frozenset()
    answers: frozenset[str] = frozenset()
    ended_by_beamline: dict[str, tuple[str, ...]] = field(
        default_factory=dict[str, tuple[str, ...]]
    )
    opened: list[str] = field(default_factory=list[str])
    closed: list[str] = field(default_factory=list[str])

    def pursuits(self) -> tuple[Pursuit, ...]:
        return self.running

    def ended(self, beamline: str) -> tuple[str, ...]:
        return self.ended_by_beamline.get(beamline, ())

    def answered(self, inquiry_id: str) -> bool:
        return inquiry_id in self.answers

    def open_round(self, pursuit_id: str, execution_id: str) -> str | None:
        if pursuit_id in self.refuses:
            raise RuntimeError(f"{pursuit_id} is out of budget")
        self.opened.append(pursuit_id)
        return f"inquiry-{execution_id}"

    def close_round(self, pursuit_id: str, index: int) -> Closed:
        if pursuit_id in self.refuses:
            raise RuntimeError(f"{pursuit_id} would not close")
        self.closed.append(pursuit_id)
        return Closed(outcome="Advanced", dispatched_id="x1")


def test_every_running_pursuit_gets_a_turn() -> None:
    record = _Record(
        running=(
            Pursuit(pursuit_id="a", beamline="2-bm"),
            Pursuit(pursuit_id="b", beamline="7-bm"),
        ),
        ended_by_beamline={"2-bm": ("e1",), "7-bm": ("e2",)},
    )

    assert turn_every(record) == 2
    assert record.opened == ["a", "b"]


def test_a_pursuit_that_refuses_does_not_cost_the_others_their_turn() -> None:
    """The one thing this pass adds over turning a single pursuit. A budget
    can run out between the listing and the open, and that is a fact about
    one pursuit rather than a fault in the loop."""
    record = _Record(
        running=(
            Pursuit(pursuit_id="broke", beamline="2-bm"),
            Pursuit(pursuit_id="fine", beamline="7-bm"),
        ),
        refuses=frozenset({"broke"}),
        ended_by_beamline={"2-bm": ("e1",), "7-bm": ("e2",)},
    )

    assert turn_every(record) == 1
    assert record.opened == ["fine"]


def test_a_pass_over_pursuits_with_nothing_to_do_moves_none() -> None:
    record = _Record(running=(Pursuit(pursuit_id="a", beamline="2-bm"),))

    assert turn_every(record) == 0


def test_a_pursuit_waiting_on_a_thinker_is_not_counted_as_moved() -> None:
    waiting = Round(index=0, execution_id="e1", inquiry_id="i0")
    record = _Record(running=(Pursuit(pursuit_id="a", beamline="2-bm", rounds=(waiting,)),))

    assert turn_every(record) == 0
    assert record.closed == []


def test_a_pursuit_whose_answer_landed_is_closed_and_counted() -> None:
    waiting = Round(index=0, execution_id="e1", inquiry_id="i0")
    record = _Record(
        running=(Pursuit(pursuit_id="a", beamline="2-bm", rounds=(waiting,)),),
        answers=frozenset({"i0"}),
    )

    assert turn_every(record) == 1
    assert record.closed == ["a"]


def test_a_turner_configuration_needs_no_beamline_and_no_scopes() -> None:
    """A conductor's file is refused without a beamline. This one is not,
    because a turner watches every pursuit the record will show it."""
    config = turner_from_mapping({"keeper": {"base_url": "https://keeper:8443", "token": "t"}})

    assert config.base_url == "https://keeper:8443"
    assert config.pause > 0


def test_a_pause_of_zero_is_refused_rather_than_spinning() -> None:
    with pytest.raises(ConfigError, match="above zero"):
        turner_from_mapping(
            {"keeper": {"base_url": "https://keeper:8443", "token": "t"}, "turn": {"pause": 0}}
        )
