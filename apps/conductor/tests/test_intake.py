"""What the loop does with what AROC hands it, and what keeps it alive.

Every seam here is a double and nothing sleeps. The loop's own clock is a
parameter for that reason: a test asserting that a failure costs a backoff
should not be the thing that spends it.

A turn is one pass: ask, maybe claim, maybe walk. `_turns` bounds the loop
the way a signal handler would, which is the only way a `serve` ever
returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conductor.claims import Claim, Ledger
from conductor.intake import serve
from conductor.outcomes import Done, Refused
from conductor.procedure import Acquire, Move, Procedure
from conductor.seams import Assignment
from tests._fakes import CollectingAroc, RecordingAcquisition, RecordingControl

if TYPE_CHECKING:
    from collections.abc import Callable

BEAMLINE = "2-bm"
EXECUTION = "an-execution"


def _turns(count: int) -> Callable[[], bool]:
    """A `keep_going` that allows exactly this many passes."""
    remaining = iter(range(count))
    return lambda: next(remaining, None) is not None


def _assignment(execution_id: str = EXECUTION, *, name: str = "tomography") -> Assignment:
    return Assignment(
        execution_id=execution_id,
        procedure=Procedure(
            name=name,
            steps=(
                Move(record="2bmb:m1", to=1.0),
                Acquire(plan="tomo_scan", claim=Claim.over("2bmb:cam1:")),
            ),
        ),
        step_ids=("step-one", "step-two"),
    )


def _serve(
    aroc: CollectingAroc,
    *,
    turns: int = 1,
    ledger: Ledger | None = None,
    slept: list[float] | None = None,
    said: list[str] | None = None,
) -> tuple[RecordingControl, RecordingAcquisition]:
    control = RecordingControl()
    acquisition = RecordingAcquisition()
    serve(
        aroc,
        BEAMLINE,
        control=control,
        acquisition=acquisition,
        wait=7.0,
        backoff=3.0,
        ledger=ledger,
        keep_going=_turns(turns),
        pause=(slept if slept is not None else []).append,
        note=(said if said is not None else []).append,
    )
    return control, acquisition


def test_an_idle_beamline_asks_again_and_claims_nothing() -> None:
    """The state a conductor spends almost all of its time in.

    Each ask is already a held request, so a turn that finds nothing has
    waited the whole time it was going to wait. Anything added on top
    would be latency charged to the next dispatch for no reason.
    """
    aroc = CollectingAroc()
    slept: list[float] = []

    _serve(aroc, turns=3, slept=slept)

    assert aroc.asked == [(BEAMLINE, 7.0)] * 3
    assert aroc.claimed == []
    assert slept == []


def test_work_dispatched_here_is_claimed_and_then_walked() -> None:
    """The whole point, in one turn."""
    aroc = CollectingAroc(waiting=[_assignment()])

    control, acquisition = _serve(aroc)

    assert aroc.claimed == [EXECUTION]
    assert control.moves == [("2bmb:m1", 1.0)]
    assert [plan for plan, _, _ in acquisition.asked] == ["tomo_scan"]


def test_every_step_is_reported_against_the_execution_that_was_claimed() -> None:
    """A walk reports by index, so the binding is what says which record.

    Getting this wrong would file a beamline's whole day against one
    execution, and every report would be accepted.
    """
    aroc = CollectingAroc(waiting=[_assignment()])

    _serve(aroc)

    assert [(execution, index) for execution, index, _ in aroc.reported] == [
        (EXECUTION, 0),
        (EXECUTION, 1),
    ]
    assert all(isinstance(outcome, Done) for _, _, outcome in aroc.reported)
    assert aroc.finished == [EXECUTION]


def test_an_execution_another_conductor_claimed_first_is_not_walked() -> None:
    """Losing the race is ordinary, and the loser must touch no hardware.

    A conductor that walked anyway would be the second driver on devices
    the winner is holding, which is the collision this package exists to
    prevent, arranged by the package itself.
    """
    aroc = CollectingAroc(waiting=[_assignment()], grants_claims=False)

    control, acquisition = _serve(aroc)

    assert aroc.claimed == [EXECUTION]
    assert control.moves == []
    assert acquisition.asked == []
    assert aroc.reported == []


def test_a_conductor_that_lost_one_claim_goes_back_for_the_next() -> None:
    """A lost claim is not a failure, so it costs no backoff."""
    aroc = CollectingAroc(waiting=[_assignment()], grants_claims=False)
    slept: list[float] = []

    _serve(aroc, turns=2, slept=slept)

    assert len(aroc.asked) == 2
    assert slept == []


def test_an_aroc_that_cannot_be_reached_is_waited_out_and_asked_again() -> None:
    """The failure a beamline sees most: AROC restarting, or a network blip.

    The loop has one policy for everything that goes wrong, so this is
    also the arm that catches a refusal nobody will ever grant. A daemon
    that exited instead would hand a service manager a crash loop, with
    the same messages spread over process lifetimes.
    """
    aroc = CollectingAroc(refuses_take=ConnectionError("aroc.example did not answer"))
    slept: list[float] = []
    said: list[str] = []

    _serve(aroc, turns=3, slept=slept, said=said)

    assert len(aroc.asked) == 3
    assert slept == [3.0, 3.0, 3.0]
    assert any("did not answer" in line for line in said)


def test_a_failure_says_which_exception_it_was() -> None:
    """The cost of catching broadly, paid down by what the line carries.

    A bug in an adapter reaches the same arm as an unreachable AROC, so
    the type and the message are the only things that tell them apart.
    """
    aroc = CollectingAroc(refuses_take=KeyError("step_id"))
    said: list[str] = []

    _serve(aroc, said=said)

    assert any("KeyError" in line for line in said)


def test_a_report_that_cannot_be_delivered_does_not_end_the_loop() -> None:
    """The walk stops, the execution stays open, and the conductor carries on.

    An execution left open is the accurate record of a driver that could
    not report rather than a gap in one, so nothing here reaches for a
    closing call over a connection that has just failed.
    """
    aroc = CollectingAroc(
        waiting=[_assignment(), _assignment("a-later-execution")],
        refuses_report=ConnectionError("the socket went away"),
    )

    _serve(aroc, turns=2)

    assert aroc.finished == []
    assert aroc.claimed == [EXECUTION, "a-later-execution"]


def test_the_ledger_it_is_given_is_the_one_the_walk_holds_claims_in() -> None:
    """Two conductors in one process share a ledger or share nothing.

    A claim held outside this loop has to refuse a step inside it, and
    the only way that happens is if the ledger handed in is the one the
    walk consults.
    """
    book = Ledger()
    book.acquire("something-else", Claim.over("2bmb:m1"))
    aroc = CollectingAroc(waiting=[_assignment()])

    control, _ = _serve(aroc, ledger=book)

    assert control.moves == []
    assert isinstance(aroc.reported[0][2], Refused)


def test_a_loop_that_is_told_to_stop_before_its_first_turn_asks_nothing() -> None:
    """`keep_going` is checked before the ask, not after it.

    A conductor stopping would otherwise hold one more request open for
    the whole wait, which is how a shutdown takes half a minute.
    """
    aroc = CollectingAroc(waiting=[_assignment()])

    _serve(aroc, turns=0)

    assert aroc.asked == []
    assert aroc.claimed == []


def test_a_walk_in_progress_finishes_before_a_stop_takes_effect() -> None:
    """Checked between turns rather than inside one.

    A conductor that dropped a procedure half-walked would leave the
    hardware wherever the last step put it, with the record saying
    nothing about why the rest never ran.
    """
    aroc = CollectingAroc(waiting=[_assignment()])

    _serve(aroc, turns=1)

    assert len(aroc.reported) == 2
    assert aroc.finished == [EXECUTION]
