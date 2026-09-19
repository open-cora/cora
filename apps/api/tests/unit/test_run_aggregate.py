"""The Run aggregate: its fold, its round trip, and its one value object.

The round trip is the load-bearing one. The external reference leaves as
two loose strings and comes back as a pair that validates itself, and the
two halves are written in different modules, so nothing but a test run
against both at once says they still agree.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from aroc.execution.aggregates.run import (
    RUN_STREAM_TYPE,
    RunAborted,
    RunCompleted,
    RunFailed,
    RunPaused,
    RunReported,
    RunResumed,
    RunStatus,
    fold,
    from_stored,
    to_payload,
)
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.shared.identifier import (
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
    InvalidIdentifierError,
)

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 11, 15, tzinfo=UTC)

_PARAMETERS: dict[str, Any] = {"exposure_seconds": 0.25}


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=RUN_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _recorded(value: str = "f1e2d3c4") -> RunReported:
    return RunReported(
        run_id=uuid4(),
        plan_id=uuid4(),
        parameters=_PARAMETERS,
        external_ref_scheme="bluesky-run-uid",
        external_ref_value=value,
        occurred_at=_WHEN,
    )


def test_the_stored_payload_carries_the_reference_as_two_flat_strings() -> None:
    """The payload boundary, asserted on the payload itself.

    Events carry primitives, so the pair is flattened here and rebuilt by
    the fold. A field added to this event would be written into a log
    that cannot be edited, and no other test in this file would notice.
    """
    event = _recorded()

    assert to_payload(event) == {
        "run_id": str(event.run_id),
        "plan_id": str(event.plan_id),
        "parameters": _PARAMETERS,
        "external_ref_scheme": "bluesky-run-uid",
        "external_ref_value": "f1e2d3c4",
        "occurred_at": _WHEN.isoformat(),
    }


def test_folding_the_genesis_event_gives_the_run_it_describes() -> None:
    event = _recorded()

    run = fold([event])

    assert run is not None
    assert run.id == event.run_id
    assert run.plan_id == event.plan_id
    assert run.parameters == _PARAMETERS
    assert run.external_ref == Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")


def test_folding_an_empty_stream_gives_no_run() -> None:
    assert fold([]) is None


@pytest.mark.parametrize(
    ("ending", "status"),
    [
        (RunCompleted, RunStatus.COMPLETED),
        (RunAborted, RunStatus.ABORTED),
        (RunFailed, RunStatus.FAILED),
    ],
    ids=["completed", "aborted", "failed"],
)
def test_each_ending_folds_to_its_own_status(
    ending: type[RunCompleted | RunAborted | RunFailed], status: RunStatus
) -> None:
    """The status is computed here and stored nowhere.

    No payload carries it, so this mapping is the only place the two can
    disagree, and a table is what makes two events folding to one status
    visible as two rows reporting the same thing.
    """
    genesis = _recorded()

    run = fold([genesis, ending(run_id=genesis.run_id, occurred_at=_WHEN)])

    assert run is not None
    assert run.status is status
    assert run.has_ended


_TERMINALITY: dict[RunStatus, bool] = {
    RunStatus.RUNNING: False,
    RunStatus.PAUSED: False,
    RunStatus.COMPLETED: True,
    RunStatus.ABORTED: True,
    RunStatus.FAILED: True,
}
"""Which statuses close a stream, pinned member by member.

Written out here rather than derived, because a derivation would agree
with `is_terminal` however wrong it was. A sixth status added without
deciding which group it joins fails the test below rather than defaulting
to live and quietly admitting an ending on a run that already ended.
"""


def test_every_status_declares_whether_it_closes_the_stream() -> None:
    assert {status: status.is_terminal for status in RunStatus} == _TERMINALITY


def test_a_paused_run_has_not_ended() -> None:
    """The distinction `has_ended` exists to draw, at the one point it bites.

    Paused is not Running and is also not over. Reading terminality as
    "not Running" gives the same answer for every other status and the
    wrong one here, which would refuse all three endings on a paused run.
    """
    genesis = _recorded()

    run = fold([genesis, RunPaused(run_id=genesis.run_id, occurred_at=_WHEN)])

    assert run is not None
    assert run.status is RunStatus.PAUSED
    assert not run.has_ended


def test_a_resumed_run_is_indistinguishable_from_one_that_never_paused() -> None:
    """The only status this machine revisits, and what that costs a reader.

    The fold reports where the stream ends up, not how it got there, so a
    run that paused and carried on is indistinguishable by status from
    one that never paused. That is the intended trade: the events are
    still there for a reader who wants them, and the status stays a
    reading of history rather than a tally of it.
    """
    genesis = _recorded()
    cycle = [
        genesis,
        RunPaused(run_id=genesis.run_id, occurred_at=_WHEN),
        RunResumed(run_id=genesis.run_id, occurred_at=_WHEN),
    ]

    resumed = fold(cycle)
    untouched = fold([genesis])

    assert resumed is not None
    assert untouched is not None
    assert resumed.status is RunStatus.RUNNING
    assert resumed == untouched


def test_an_ending_after_a_cycle_reaches_its_terminal() -> None:
    """A stream can hold several transitions before the one that closes it.

    Every other test here folds at most two events. This one checks that
    the ending arms read the state in front of them rather than assuming
    they follow the genesis.
    """
    genesis = _recorded()

    run = fold(
        [
            genesis,
            RunPaused(run_id=genesis.run_id, occurred_at=_WHEN),
            RunResumed(run_id=genesis.run_id, occurred_at=_WHEN),
            RunCompleted(run_id=genesis.run_id, occurred_at=_WHEN),
        ]
    )

    assert run is not None
    assert run.status is RunStatus.COMPLETED


@pytest.mark.parametrize(
    "event_type",
    [RunPaused, RunResumed],
    ids=["paused", "resumed"],
)
def test_a_cycle_event_survives_the_round_trip_through_its_stored_payload(
    event_type: type[RunPaused | RunResumed],
) -> None:
    """Two more classes on the union, so two more rows the reader must place.

    `from_stored` dispatches on a string. A class added to the union and
    not to that match is a stored row nobody can rebuild, which fails at
    read time on a log that cannot be edited.
    """
    event = event_type(run_id=uuid4(), occurred_at=_WHEN)

    assert from_stored(_stored(type(event).__name__, to_payload(event))) == event


def test_an_ending_changes_the_status_and_nothing_else() -> None:
    """An ending says when a run stopped, never what it was doing.

    The evolver's ending arms replace one field, so the plan, parameters
    and reference come through by construction. An arm rebuilding the
    whole run by hand could drop one and every status test would still
    pass.
    """
    genesis = _recorded()

    before = fold([genesis])
    after = fold([genesis, RunAborted(run_id=genesis.run_id, occurred_at=_WHEN)])

    assert before is not None
    assert after is not None
    assert (after.id, after.plan_id, after.parameters, after.external_ref) == (
        before.id,
        before.plan_id,
        before.parameters,
        before.external_ref,
    )


def test_an_ending_applied_to_an_empty_stream_is_refused() -> None:
    """A terminal with no genesis before it means the log is out of order.

    Unreachable through any handler, because one loads the stream before
    deciding. Reachable by a replay that lost a row, and folding it into
    a run with no plan and no reference would be worse than failing.
    """
    with pytest.raises(ValueError, match="RunCompleted"):
        fold([RunCompleted(run_id=uuid4(), occurred_at=_WHEN)])


def test_the_folded_parameters_are_not_the_payload_dict_they_came_from() -> None:
    """Shallow copy on fold, so neither side can mutate the other.

    The immutable-collection rule in docs/reference/modeling.md cannot
    cover a freeform dict, so the copy is the defence that replaces it.
    An aliasing bug here is silent: the state would look right until
    something wrote through one reference and changed the other.
    """
    event = _recorded()

    run = fold([event])

    assert run is not None
    assert run.parameters == event.parameters
    assert run.parameters is not event.parameters


def test_an_event_survives_the_round_trip_through_its_stored_payload() -> None:
    event = _recorded()

    assert from_stored(_stored("RunReported", to_payload(event))) == event


def test_a_stored_row_of_an_unknown_event_type_is_refused() -> None:
    """The name here is one no version of this aggregate has emitted.

    It used to be `RunCompleted`, which the commit adding the terminals
    turned into a real event and this test into a false negative. A name
    for this case has to be one nothing will plausibly add later, so it
    describes an ending this model does not draw.
    """
    with pytest.raises(ValueError, match="Unknown Run event_type"):
        from_stored(_stored("RunEvaporated", to_payload(_recorded())))


def test_a_stored_row_missing_a_field_is_refused_by_event_not_by_field() -> None:
    """The wrap is what makes the error name the event.

    Without it a bad row raises `KeyError` from inside the builder, which
    says which field was missing and not which event could not be
    rebuilt.
    """
    payload = to_payload(_recorded())
    del payload["external_ref_value"]

    with pytest.raises(ValueError, match="Malformed RunReported"):
        from_stored(_stored("RunReported", payload))


def test_a_stored_reference_that_no_longer_passes_its_bounds_fails_the_fold() -> None:
    """Re-validation on the way out, not only on the way in.

    A row can only hold a reference the edge accepted, so this state is
    unreachable through the API today. It becomes reachable the day a
    bound is tightened, and the fold refusing is what turns that into a
    visible failure rather than a run whose reference nothing could have
    written.
    """
    payload = to_payload(_recorded())
    payload["external_ref_value"] = "x" * (IDENTIFIER_VALUE_MAX_LENGTH + 1)
    row = _stored("RunReported", payload)

    with pytest.raises(InvalidIdentifierError):
        fold([from_stored(row)])
