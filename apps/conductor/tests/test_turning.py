"""What one pass over a pursuit does, against a record that is a double.

Every case here is about the decision rather than the wire, so the port is
a recording stub. The one thing worth saying about it is that it counts
calls: several of these assert that a pass did *not* ask something, which
is how the sequencing rules show up from outside.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from conductor.turning import (
    Closed,
    Idled,
    Opened,
    Pursuit,
    Round,
    Settled,
    Waited,
    turn_once,
)


@dataclass
class _Record:
    """A pursuit record that answers from what it was handed."""

    ended_executions: tuple[str, ...] = ()
    answers: frozenset[str] = frozenset()
    closes_as: Closed = field(default_factory=lambda: Closed(outcome="Advanced"))
    refuses_open: bool = False

    opened: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    closed: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    asked_ended_for: list[str] = field(default_factory=list[str])

    def pursuits(self) -> list[Pursuit]:
        return []

    def ended(self, beamline: str) -> tuple[str, ...]:
        self.asked_ended_for.append(beamline)
        return self.ended_executions

    def answered(self, inquiry_id: str) -> bool:
        return inquiry_id in self.answers

    def open_round(self, pursuit_id: str, execution_id: str) -> str | None:
        self.opened.append((pursuit_id, execution_id))
        if self.refuses_open:
            return None
        return f"inquiry-for-{execution_id}"

    def close_round(self, pursuit_id: str, index: int) -> Closed:
        self.closed.append((pursuit_id, index))
        return self.closes_as


def _pursuit(*rounds: Round, beamline: str = "19-bm") -> Pursuit:
    return Pursuit(pursuit_id="p1", beamline=beamline, rounds=rounds)


def test_a_pursuit_with_no_rounds_asks_about_the_oldest_ended_execution() -> None:
    record = _Record(ended_executions=("older", "newer"))

    turn = turn_once(record, _pursuit())

    assert turn == Opened(pursuit_id="p1", execution_id="older", inquiry_id="inquiry-for-older")
    assert record.opened == [("p1", "older")]


def test_a_pursuit_asks_at_its_own_beamline_and_no_other() -> None:
    record = _Record(ended_executions=("e1",))

    turn_once(record, _pursuit(beamline="7-bm"))

    assert record.asked_ended_for == ["7-bm"]


def test_an_execution_a_pursuit_already_observed_is_not_asked_about_again() -> None:
    record = _Record(ended_executions=("seen", "fresh"))
    already = Round(index=0, execution_id="seen", inquiry_id="i0", outcome="Advanced")

    turn = turn_once(record, _pursuit(already))

    assert isinstance(turn, Opened)
    assert turn.execution_id == "fresh"


def test_every_ended_execution_already_observed_leaves_the_pass_idle() -> None:
    record = _Record(ended_executions=("seen",))
    already = Round(index=0, execution_id="seen", inquiry_id="i0", outcome="Advanced")

    turn = turn_once(record, _pursuit(already))

    assert turn == Idled(pursuit_id="p1")
    assert record.opened == []


def test_an_open_round_whose_inquiry_is_unanswered_waits_and_opens_nothing() -> None:
    record = _Record(ended_executions=("fresh",))
    waiting = Round(index=0, execution_id="seen", inquiry_id="i0")

    turn = turn_once(record, _pursuit(waiting))

    assert turn == Waited(pursuit_id="p1", inquiry_id="i0")
    assert record.opened == []
    assert record.closed == []


def test_an_open_round_whose_inquiry_is_answered_is_closed_rather_than_added_to() -> None:
    record = _Record(
        ended_executions=("fresh",),
        answers=frozenset({"i0"}),
        closes_as=Closed(outcome="Advanced", dispatched_id="x9"),
    )
    waiting = Round(index=0, execution_id="seen", inquiry_id="i0")

    turn = turn_once(record, _pursuit(waiting))

    assert turn == Settled(pursuit_id="p1", index=0, outcome="Advanced", dispatched_id="x9")
    assert record.closed == [("p1", 0)]
    assert record.opened == []


def test_the_round_closed_is_the_open_one_and_not_the_last_one() -> None:
    """An index taken from the end of the list would close the wrong round
    where an earlier one is still open, which is the shape a driver that
    counted rounds instead of reading them would produce."""
    record = _Record(answers=frozenset({"i1"}))
    rounds = (
        Round(index=0, execution_id="a", inquiry_id="i0", outcome="Advanced"),
        Round(index=1, execution_id="b", inquiry_id="i1"),
    )

    turn_once(record, _pursuit(*rounds))

    assert record.closed == [("p1", 1)]


def test_a_close_that_stops_the_pursuit_is_reported_with_its_outcome() -> None:
    record = _Record(answers=frozenset({"i0"}), closes_as=Closed(outcome="Completed"))
    waiting = Round(index=0, execution_id="seen", inquiry_id="i0")

    turn = turn_once(record, _pursuit(waiting))

    assert turn == Settled(pursuit_id="p1", index=0, outcome="Completed", dispatched_id=None)


def test_an_open_the_record_refuses_moves_on_to_the_next_execution() -> None:
    record = _Record(ended_executions=("raced", "mine"), refuses_open=True)

    turn = turn_once(record, _pursuit())

    assert turn == Idled(pursuit_id="p1")
    assert record.opened == [("p1", "raced"), ("p1", "mine")]


def test_a_pursuit_with_no_ended_executions_at_all_is_idle() -> None:
    record = _Record()

    assert turn_once(record, _pursuit()) == Idled(pursuit_id="p1")
