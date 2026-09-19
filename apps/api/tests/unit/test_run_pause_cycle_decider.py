"""The two decisions that pause a run and carry it on.

One file for two slices, for the reason the endings file gives: what is
worth checking is how the pair interacts. A pause is only legal where a
resume is not, and the other way round, so every interesting case names
both and splitting them across two files would state each twice.

The pair differs from the three endings in one way that shapes the tests
below. An ending refuses only from a terminal. These two also refuse from
a live status: pausing a paused run and resuming a running one are both
moves on a run that has not ended, and both are refused.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import (
    Run,
    RunCannotBePausedError,
    RunCannotBeResumedError,
    RunNotFoundError,
    RunPaused,
    RunResumed,
    RunStatus,
)
from aroc.execution.features.pause_run import PauseRun
from aroc.execution.features.pause_run import decide as decide_pause
from aroc.execution.features.resume_run import ResumeRun
from aroc.execution.features.resume_run import decide as decide_resume
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
_REF = Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")

type _Move = RunPaused | RunResumed

type _Decide = Callable[..., Sequence[_Move]]
"""A `Sequence` rather than a `list`, because `list` is invariant.

Each decider returns `list[RunPaused]` or `list[RunResumed]`, and neither
is assignable to `list[_Move]`. The tables only ever read what comes
back, so the covariant type is both correct and enough. Same shape the
endings file uses, and for the same reason.
"""


def _run(status: RunStatus, run_id: UUID | None = None) -> Run:
    return Run(
        id=run_id or uuid4(),
        plan_id=uuid4(),
        parameters={"exposure_seconds": 0.25},
        external_ref=_REF,
        status=status,
    )


def _pause(state: Run | None, run_id: UUID) -> Sequence[_Move]:
    return decide_pause(state, PauseRun(run_id=run_id), now=_NOW)


def _resume(state: Run | None, run_id: UUID) -> Sequence[_Move]:
    return decide_resume(state, ResumeRun(run_id=run_id), now=_NOW)


_MOVES: tuple[tuple[str, _Decide, RunStatus, type[_Move], type[Exception]], ...] = (
    ("pause", _pause, RunStatus.RUNNING, RunPaused, RunCannotBePausedError),
    ("resume", _resume, RunStatus.PAUSED, RunResumed, RunCannotBeResumedError),
)
"""Each move, the one status it is admitted from, and what it produces."""

_IDS = [label for label, _d, _from, _e, _x in _MOVES]


@pytest.mark.parametrize(
    ("decide", "admitted_from", "event_type"),
    [(decide, admitted, event) for _l, decide, admitted, event, _x in _MOVES],
    ids=_IDS,
)
def test_a_move_from_the_status_that_admits_it_emits_its_own_event(
    decide: _Decide, admitted_from: RunStatus, event_type: type[_Move]
) -> None:
    """Each verb produces its own event class, and only its own.

    Two separate tests would pass just as well with both wired to one
    decider. This table fails such a wiring on the row whose class no
    longer matches.
    """
    run_id = uuid4()

    events = decide(_run(admitted_from, run_id), run_id)

    assert events == [event_type(run_id=run_id, occurred_at=_NOW)]


@pytest.mark.parametrize(
    "decide",
    [decide for _l, decide, _from, _e, _x in _MOVES],
    ids=_IDS,
)
def test_a_move_on_a_run_that_was_never_recorded_is_refused(decide: _Decide) -> None:
    with pytest.raises(RunNotFoundError):
        decide(None, uuid4())


@pytest.mark.parametrize(
    ("decide", "error_type"),
    [(decide, error) for _l, decide, _from, _e, error in _MOVES],
    ids=_IDS,
)
@pytest.mark.parametrize(
    "already",
    [RunStatus.COMPLETED, RunStatus.ABORTED, RunStatus.FAILED],
    ids=["completed", "aborted", "failed"],
)
def test_neither_move_is_admitted_from_a_terminal(
    decide: _Decide, error_type: type[Exception], already: RunStatus
) -> None:
    """A run that ended does not pause and does not carry on.

    The endings refuse each other for a reason about disagreement between
    reporters. This is simpler: a run that is over cannot start moving
    again, and a report saying it did is one the log should not take.
    """
    run_id = uuid4()

    with pytest.raises(error_type):
        decide(_run(already, run_id), run_id)


@pytest.mark.parametrize(
    ("decide", "error_type"),
    [(decide, error) for _l, decide, _from, _e, error in _MOVES],
    ids=_IDS,
)
def test_a_move_repeated_on_the_status_it_produced_is_refused(
    decide: _Decide, error_type: type[Exception]
) -> None:
    """The case the endings have no analogue for.

    An ending is refused from a terminal, which is a status no live run
    holds. These two are refused from a status the run is live in:
    pausing what is already paused, resuming what is already running.
    Nothing is over and the move is still rejected, which is why the
    guards compare against one status rather than asking `has_ended`.
    """
    run_id = uuid4()
    produced = {_pause: RunStatus.PAUSED, _resume: RunStatus.RUNNING}[decide]

    with pytest.raises(error_type):
        decide(_run(produced, run_id), run_id)


def test_the_pair_admits_a_run_from_exactly_opposite_statuses() -> None:
    """Pause and resume are inverses, stated as one assertion.

    Written out rather than parametrized because the claim is about the
    relationship between the two rows, not about either one. A pause that
    quietly started admitting Paused would pass every table above on its
    own row and fail here.
    """
    run_id = uuid4()

    assert _pause(_run(RunStatus.RUNNING, run_id), run_id)
    assert _resume(_run(RunStatus.PAUSED, run_id), run_id)
    with pytest.raises(RunCannotBePausedError):
        _pause(_run(RunStatus.PAUSED, run_id), run_id)
    with pytest.raises(RunCannotBeResumedError):
        _resume(_run(RunStatus.RUNNING, run_id), run_id)


def test_the_refusal_names_the_status_the_run_is_actually_in() -> None:
    """Which status blocked the move is the fact the caller lacks.

    Being told a pause was refused is much less useful than being told
    the run had already been aborted, because only the second says
    whether to retry, to look for an operator, or to stop reporting.
    """
    run_id = uuid4()

    with pytest.raises(RunCannotBeResumedError) as refusal:
        _resume(_run(RunStatus.ABORTED, run_id), run_id)

    assert refusal.value.status is RunStatus.ABORTED
    assert "Aborted" in str(refusal.value)
