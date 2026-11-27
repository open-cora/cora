"""The Proposal aggregate: its events, its fold, and the round trip.

Two ways to open a stream and two to close one. The properties worth
pinning are that the closing edges are one way, that the parameters
survive the trip through the log as a document rather than as a shared
reference, that open is a null reference rather than a stored flag, and
that a proposal made with one run folds into exactly the state a plan of
that one run does.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    PlanProposed,
    Proposal,
    ProposalAdopted,
    ProposalMade,
    ProposalStatus,
    ProposalTaken,
    ProposedRun,
    evolve,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1, "num_projections": 1500}


def _made(**overrides: object) -> ProposalMade:
    fields: dict[str, object] = {
        "proposal_id": uuid4(),
        "actor_id": uuid4(),
        "operation_id": uuid4(),
        "parameters": dict(_PARAMETERS),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ProposalMade(**fields)  # pyright: ignore[reportArgumentType]


def _taken(proposal_id: object, **overrides: object) -> ProposalTaken:
    fields: dict[str, object] = {
        "proposal_id": proposal_id,
        "execution_id": uuid4(),
        "step_id": uuid4(),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ProposalTaken(**fields)  # pyright: ignore[reportArgumentType]


def _proposed(**overrides: object) -> PlanProposed:
    fields: dict[str, object] = {
        "proposal_id": uuid4(),
        "actor_id": uuid4(),
        "runs": (
            ProposedRun(operation_id=uuid4(), parameters=dict(_PARAMETERS)),
            ProposedRun(operation_id=uuid4(), parameters={"destination": "alcf"}),
        ),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return PlanProposed(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: ProposalMade | PlanProposed | ProposalTaken | ProposalAdopted) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Proposal",
        stream_id=event.proposal_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def test_folding_an_empty_stream_gives_nothing() -> None:
    assert fold([]) is None


def test_folding_a_genesis_gives_a_proposal_with_no_acquisition() -> None:
    made = _made()

    state = fold([made])

    assert state == Proposal(
        id=made.proposal_id,
        actor_id=made.actor_id,
        runs=(ProposedRun(operation_id=made.operation_id, parameters=_PARAMETERS),),
        execution_id=None,
        step_id=None,
    )


def test_a_proposal_with_no_acquisition_reads_as_not_taken() -> None:
    assert fold([_made()]).is_taken is False  # pyright: ignore[reportOptionalMemberAccess]


def test_folding_a_take_records_the_acquisition_and_makes_it_taken() -> None:
    """Both halves land, because one without the other names nothing.

    A step is an entity inside an execution rather than a stream of its
    own, so a fold that kept the step and dropped the root would leave a
    reference no reader can follow.
    """
    made = _made()
    execution_id = uuid4()
    step_id = uuid4()

    state = fold(
        [
            made,
            ProposalTaken(
                proposal_id=made.proposal_id,
                execution_id=execution_id,
                step_id=step_id,
                occurred_at=_WHEN,
            ),
        ]
    )

    assert state is not None
    assert (state.execution_id, state.step_id) == (execution_id, step_id)
    assert state.is_taken is True


def test_taking_leaves_every_other_field_unchanged() -> None:
    made = _made()

    state = fold([made, _taken(made.proposal_id)])

    assert state is not None
    assert (state.id, state.actor_id) == (made.proposal_id, made.actor_id)
    assert state.runs == (ProposedRun(operation_id=made.operation_id, parameters=_PARAMETERS),)


def test_taking_before_a_genesis_is_a_broken_stream() -> None:
    with pytest.raises(ValueError, match="ProposalTaken"):
        evolve(None, _taken(uuid4()))


def test_the_state_does_not_alias_the_parameters_the_event_carries() -> None:
    """A dict on a payload is shallow-copied into state, never shared.

    The fitness test that pins immutable collections cannot reach a
    freeform document, so this is the companion defence
    docs/reference/modeling.md asks for, tested rather than asserted.
    """
    made = _made()

    state = fold([made])

    assert state is not None
    state.runs[0].parameters["exposure_time_s"] = 99.0
    assert made.parameters["exposure_time_s"] == 0.1


def test_a_genesis_survives_the_round_trip_through_the_log() -> None:
    made = _made()

    assert from_stored(_stored(made)) == made


def test_a_take_survives_the_round_trip_through_the_log() -> None:
    taken = _taken(uuid4())

    assert from_stored(_stored(taken)) == taken


def test_an_unknown_event_type_on_this_stream_is_refused() -> None:
    stored = _stored(_made())
    unknown = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="ProposalWithdrawn",
        schema_version=stored.schema_version,
        payload=stored.payload,
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Unknown Proposal event_type"):
        from_stored(unknown)


def test_a_malformed_payload_names_the_event_and_not_the_field() -> None:
    stored = _stored(_made())
    broken = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="ProposalMade",
        schema_version=stored.schema_version,
        payload={**stored.payload, "operation_id": "not-a-uuid"},
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Malformed ProposalMade"):
        from_stored(broken)


def _adopted(proposal_id: object, **overrides: object) -> ProposalAdopted:
    fields: dict[str, object] = {
        "proposal_id": proposal_id,
        "execution_id": uuid4(),
        "step_id": uuid4(),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return ProposalAdopted(**fields)  # pyright: ignore[reportArgumentType]


def test_a_proposal_nothing_came_of_reads_as_open() -> None:
    assert fold([_made()]).status is ProposalStatus.OPEN  # pyright: ignore[reportOptionalMemberAccess]


def test_folding_an_adoption_records_the_acquisition_it_was_composed_into() -> None:
    made = _made()
    adopted = _adopted(made.proposal_id)

    state = fold([made, adopted])

    assert state is not None
    assert (state.execution_id, state.step_id) == (adopted.execution_id, adopted.step_id)


def test_an_adopted_proposal_and_a_taken_one_differ_only_in_the_status() -> None:
    """Both close the proposal and both write the same two ids. The word
    is the only thing that says which way it closed, which is why it is
    derived from the event rather than read off a payload."""
    made = _made()
    execution_id, step_id = uuid4(), uuid4()

    adopted = fold([made, _adopted(made.proposal_id, execution_id=execution_id, step_id=step_id)])
    taken = fold([made, _taken(made.proposal_id, execution_id=execution_id, step_id=step_id)])

    assert adopted is not None
    assert taken is not None
    assert adopted.status is ProposalStatus.ADOPTED
    assert taken.status is ProposalStatus.TAKEN
    assert (adopted.execution_id, adopted.step_id) == (taken.execution_id, taken.step_id)


def test_an_adopted_proposal_is_no_longer_open() -> None:
    """`is_taken` answers whether anything came of it, either way, which
    is the bit the read side has always filtered on."""
    made = _made()

    state = fold([made, _adopted(made.proposal_id)])

    assert state is not None
    assert state.is_taken is True


def test_an_adoption_survives_the_round_trip_through_the_log() -> None:
    made = _made()
    adopted = _adopted(made.proposal_id)

    assert from_stored(_stored(adopted)) == adopted
    assert fold([from_stored(_stored(event)) for event in (made, adopted)]) == fold([made, adopted])


def test_adopting_a_proposal_that_was_never_made_is_refused() -> None:
    with pytest.raises(ValueError, match="ProposalAdopted"):
        evolve(None, _adopted(uuid4()))


def test_folding_a_plan_gives_its_runs_in_the_order_they_were_proposed() -> None:
    proposed = _proposed()

    state = fold([proposed])

    assert state == Proposal(
        id=proposed.proposal_id,
        actor_id=proposed.actor_id,
        runs=proposed.runs,
        status=ProposalStatus.OPEN,
        execution_id=None,
        step_id=None,
    )


def test_a_proposal_made_with_one_run_folds_into_the_state_a_plan_of_that_run_does() -> None:
    """The reading that lets every proposal already on the record keep
    working: nothing that reads a fold has to know which genesis wrote it."""
    made = _made()
    one = _proposed(
        proposal_id=made.proposal_id,
        actor_id=made.actor_id,
        runs=(ProposedRun(operation_id=made.operation_id, parameters=dict(_PARAMETERS)),),
    )

    assert fold([made]) == fold([one])


def test_a_plan_of_several_runs_has_no_sole_run_and_a_proposal_of_one_does() -> None:
    plan = fold([_proposed()])
    made = _made()
    single = fold([made])

    assert plan is not None
    assert single is not None
    assert plan.sole_run is None
    assert single.sole_run == ProposedRun(operation_id=made.operation_id, parameters=_PARAMETERS)


def test_a_plan_survives_the_round_trip_through_the_log() -> None:
    proposed = _proposed()

    assert from_stored(_stored(proposed)) == proposed


def test_a_plan_keeps_no_reference_to_the_parameters_its_event_carries() -> None:
    proposed = _proposed()

    state = fold([proposed])

    assert state is not None
    state.runs[1].parameters["destination"] = "somewhere else"
    assert proposed.runs[1].parameters["destination"] == "alcf"


def test_a_plan_whose_run_names_no_operation_is_refused_by_the_event_and_not_the_run() -> None:
    stored = _stored(_proposed())
    runs = [dict(run) for run in stored.payload["runs"]]
    runs[1]["operation_id"] = "not-a-uuid"
    broken = StoredEvent(
        position=stored.position,
        event_id=stored.event_id,
        stream_type=stored.stream_type,
        stream_id=stored.stream_id,
        version=stored.version,
        event_type="PlanProposed",
        schema_version=stored.schema_version,
        payload={**stored.payload, "runs": runs},
        correlation_id=stored.correlation_id,
        causation_id=stored.causation_id,
        occurred_at=stored.occurred_at,
        recorded_at=stored.recorded_at,
    )

    with pytest.raises(ValueError, match="Malformed PlanProposed"):
        from_stored(broken)


def test_adopting_a_plan_closes_it_the_way_it_closes_a_proposal_of_one_run() -> None:
    proposed = _proposed()
    adopted = _adopted(proposed.proposal_id)

    state = fold([proposed, adopted])

    assert state is not None
    assert state.status is ProposalStatus.ADOPTED
    assert (state.execution_id, state.step_id) == (adopted.execution_id, adopted.step_id)
    assert state.runs == proposed.runs
