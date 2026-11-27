"""The decision that proposing a plan produces.

`make_proposal`'s checks made of every run, and the bound on how many
runs a plan holds. What is worth pinning beyond that is that one bad run
refuses the whole plan, that a refusal says which run, and that nothing
needing a beamline is asked here at all.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_MAX_RUNS,
    InvalidProposalParametersError,
    InvalidProposalRunsError,
    PlanProposed,
    Proposal,
    ProposalAlreadyExistsError,
    ProposedRun,
)
from keeper.counsel.features.propose_plan import ProposePlan, ProposePlanContext, decide
from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationName,
    OperationStatus,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
_OPEN_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_TYPED_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_time_s": {"type": "number"}},
    "required": ["exposure_time_s"],
}


def _operation(
    name: str,
    schema: dict[str, Any] | None = None,
    status: OperationStatus = OperationStatus.ACTIVE,
    drives_devices: bool | None = None,
) -> Operation:
    return Operation(
        id=uuid4(),
        name=OperationName(name),
        parameters_schema=schema if schema is not None else _OPEN_SCHEMA,
        status=status,
        drives_devices=drives_devices,
    )


def _context(*operations: Operation) -> ProposePlanContext:
    return ProposePlanContext(operations={operation.id: operation for operation in operations})


def _run(operation: Operation, **parameters: Any) -> ProposedRun:
    return ProposedRun(operation_id=operation.id, parameters=dict(parameters))


def _decide(runs: tuple[ProposedRun, ...], context: ProposePlanContext) -> list[PlanProposed]:
    return decide(
        None, ProposePlan(runs=runs), context=context, actor_id=uuid4(), now=_NOW, new_id=uuid4()
    )


def test_proposing_a_plan_emits_one_event_holding_the_runs_in_order() -> None:
    collect, move = _operation("collect", _TYPED_SCHEMA), _operation("move")
    runs = (_run(collect, exposure_time_s=0.1), _run(move, to="alcf"), _run(move, to="aps"))
    actor_id, new_id = uuid4(), uuid4()

    events = decide(
        None,
        ProposePlan(runs=runs),
        context=_context(collect, move),
        actor_id=actor_id,
        now=_NOW,
        new_id=new_id,
    )

    assert events == [
        PlanProposed(proposal_id=new_id, actor_id=actor_id, runs=runs, occurred_at=_NOW)
    ]


def test_a_plan_of_one_run_is_accepted() -> None:
    move = _operation("move")

    events = _decide((_run(move),), _context(move))

    assert len(events[0].runs) == 1


def test_a_plan_of_the_most_runs_a_proposal_holds_is_accepted() -> None:
    move = _operation("move")

    events = _decide(tuple(_run(move) for _ in range(PROPOSAL_MAX_RUNS)), _context(move))

    assert len(events[0].runs) == PROPOSAL_MAX_RUNS


def test_the_most_runs_a_plan_holds_is_the_sixteen_its_prose_states() -> None:
    assert PROPOSAL_MAX_RUNS == 16, (
        "The bound is written out as sixteen in the Counsel page, in the plan tool's "
        "description an agent reads, in the proposal summary module and in the "
        "migration that made room for plans. Move them with it, then move this."
    )


@pytest.mark.parametrize("count", [0, PROPOSAL_MAX_RUNS + 1])
def test_a_plan_of_no_runs_or_too_many_is_refused(count: int) -> None:
    move = _operation("move")

    with pytest.raises(InvalidProposalRunsError, match=f"puts forward {count}"):
        _decide(tuple(_run(move) for _ in range(count)), _context(move))


def test_one_run_of_a_retired_operation_refuses_the_whole_plan() -> None:
    collect = _operation("collect")
    retired = _operation("move", status=OperationStatus.RETIRED)

    with pytest.raises(OperationCannotBeCitedError) as caught:
        _decide((_run(collect), _run(retired)), _context(collect, retired))

    assert caught.value.operation_id == retired.id


def test_every_retirement_is_asked_about_before_any_values_are() -> None:
    """A bad value in the first run does not hide a retired operation in the second."""
    collect = _operation("collect", _TYPED_SCHEMA)
    retired = _operation("move", status=OperationStatus.RETIRED)

    with pytest.raises(OperationCannotBeCitedError):
        _decide(
            (_run(collect, exposure_time_s="half a second"), _run(retired)),
            _context(collect, retired),
        )


def test_values_one_runs_schema_refuses_refuse_the_plan_and_name_the_run() -> None:
    move = _operation("move")
    collect = _operation("collect", _TYPED_SCHEMA)

    with pytest.raises(InvalidProposalParametersError, match="Run 1 cannot run"):
        _decide(
            (_run(move), _run(collect, exposure_time_s="half a second")),
            _context(move, collect),
        )


def test_proposing_onto_a_live_stream_is_refused() -> None:
    move = _operation("move")
    existing = Proposal(id=uuid4(), actor_id=uuid4(), runs=(_run(move),))

    with pytest.raises(ProposalAlreadyExistsError):
        decide(
            existing,
            ProposePlan(runs=(_run(move),)),
            context=_context(move),
            actor_id=uuid4(),
            now=_NOW,
            new_id=uuid4(),
        )


def test_an_undeclared_operation_is_not_refused_when_the_plan_is_proposed() -> None:
    """Device use is decided where a plan is adopted, and may be declared
    between the two, so nothing about it is asked here."""
    collect = _operation("collect", drives_devices=None)
    move = _operation("move", drives_devices=None)

    events = _decide((_run(collect), _run(move)), _context(collect, move))

    assert len(events) == 1


def test_the_proposer_comes_from_the_parameter_and_not_from_the_command() -> None:
    move = _operation("move")
    actor_id: UUID = uuid4()

    events = decide(
        None,
        ProposePlan(runs=(_run(move),)),
        context=_context(move),
        actor_id=actor_id,
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].actor_id == actor_id
    assert "actor_id" not in ProposePlan.__dataclass_fields__
    assert "occurred_at" not in ProposePlan.__dataclass_fields__
