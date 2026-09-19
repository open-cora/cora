"""The three decisions that end a run.

One file for three slices, against the cross-slice grain, and worth
saying why. These deciders are not three behaviours; they are one
behaviour with three outputs, and every interesting case is about how
they interact: an ending refusing another ending, three reaching three
different terminals, one refusal naming the status a different verb
produced. Split across three files those cases either disappear or get
written three times.

The tables are what carry it. Each row names a verb, and a row that
passed because two verbs share a handler would show up as two rows
reporting the same terminal.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import (
    Run,
    RunAborted,
    RunCannotBeAbortedError,
    RunCannotBeCompletedError,
    RunCannotBeFailedError,
    RunCompleted,
    RunFailed,
    RunNotFoundError,
    RunStatus,
)
from aroc.execution.features.abort_run import AbortRun
from aroc.execution.features.abort_run import decide as decide_abort
from aroc.execution.features.complete_run import CompleteRun
from aroc.execution.features.complete_run import decide as decide_complete
from aroc.execution.features.fail_run import FailRun
from aroc.execution.features.fail_run import decide as decide_fail
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
_REF = Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")

type _Ending = RunCompleted | RunAborted | RunFailed
"""The three events an ending can produce, and nothing else.

Narrower than `RunEvent`, which also holds the genesis. The tables below
construct one of these from a class object, and the genesis takes four
more fields, so a union carrying it would not type-check at the call.
"""

type _Decide = Callable[..., Sequence[_Ending]]
"""A `Sequence` rather than a `list`, because `list` is invariant.

Each decider returns `list[RunCompleted]` or one of its siblings, and
none of those is assignable to `list[_Ending]`. The tables only ever
read what comes back, so the covariant type is both correct and enough.
"""


def _run(status: RunStatus, run_id: UUID | None = None) -> Run:
    return Run(
        id=run_id or uuid4(),
        plan_id=uuid4(),
        parameters={"exposure_seconds": 0.25},
        external_ref=_REF,
        status=status,
    )


def _complete(state: Run | None, run_id: UUID) -> Sequence[_Ending]:
    return decide_complete(state, CompleteRun(run_id=run_id), now=_NOW)


def _abort(state: Run | None, run_id: UUID) -> Sequence[_Ending]:
    return decide_abort(state, AbortRun(run_id=run_id), now=_NOW)


def _fail(state: Run | None, run_id: UUID) -> Sequence[_Ending]:
    return decide_fail(state, FailRun(run_id=run_id), now=_NOW)


_ENDINGS: tuple[tuple[str, _Decide, type[_Ending], type[Exception]], ...] = (
    ("complete", _complete, RunCompleted, RunCannotBeCompletedError),
    ("abort", _abort, RunAborted, RunCannotBeAbortedError),
    ("fail", _fail, RunFailed, RunCannotBeFailedError),
)


@pytest.mark.parametrize(
    ("decide", "event_type"),
    [(decide, event_type) for _label, decide, event_type, _error in _ENDINGS],
    ids=[label for label, _d, _e, _x in _ENDINGS],
)
def test_ending_a_running_run_emits_that_endings_own_event(
    decide: _Decide, event_type: type[_Ending]
) -> None:
    """Each verb produces its own event class, and only its own.

    Three separate tests would pass just as well with two of them wired
    to one decider. This table fails such a wiring on the row whose class
    no longer matches.
    """
    run_id = uuid4()

    events = decide(_run(RunStatus.RUNNING, run_id), run_id)

    assert events == [event_type(run_id=run_id, occurred_at=_NOW)]


@pytest.mark.parametrize(
    "decide",
    [decide for _label, decide, _event, _error in _ENDINGS],
    ids=[label for label, _d, _e, _x in _ENDINGS],
)
def test_ending_a_run_that_was_never_recorded_is_refused(decide: _Decide) -> None:
    with pytest.raises(RunNotFoundError):
        decide(None, uuid4())


@pytest.mark.parametrize(
    ("decide", "error_type"),
    [(decide, error) for _label, decide, _event, error in _ENDINGS],
    ids=[label for label, _d, _e, _x in _ENDINGS],
)
@pytest.mark.parametrize(
    "already",
    [RunStatus.COMPLETED, RunStatus.ABORTED, RunStatus.FAILED],
    ids=["completed", "aborted", "failed"],
)
def test_every_ending_is_refused_from_every_terminal(
    decide: _Decide, error_type: type[Exception], already: RunStatus
) -> None:
    """Nine cells, and every one of them a refusal.

    The diagonal is the obvious case: completing a completed run. The off
    diagonal is the one worth pinning, because it is where a plausible
    reading goes wrong. An engine that reported success and then crashed
    on the way out arrives as fail-after-complete, and the honest answer
    is that this system cannot tell which report was right, so it keeps
    the first and surfaces the disagreement.
    """
    run_id = uuid4()

    with pytest.raises(error_type):
        decide(_run(already, run_id), run_id)


def test_the_refusal_names_the_status_the_run_is_actually_in() -> None:
    """Which ending already happened is the fact the caller lacks.

    Being told a run already ended is much less useful than being told it
    ended by being aborted, because only the second tells the caller
    whether to look for data or for an operator.
    """
    run_id = uuid4()

    with pytest.raises(RunCannotBeCompletedError) as refusal:
        _complete(_run(RunStatus.ABORTED, run_id), run_id)

    assert refusal.value.status is RunStatus.ABORTED
    assert "Aborted" in str(refusal.value)
