"""The decision: what proposing a plan produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters, and the operations arrive on the context, precisely so this
function has nothing to fetch and nothing to invent.

`actor_id` arrives as a parameter rather than on the command, because it
is not the caller's to set, which is `make_proposal`'s arrangement too.
"""

from datetime import datetime
from uuid import UUID

from keeper.counsel.aggregates.proposal import (
    PROPOSAL_MAX_RUNS,
    InvalidProposalParametersError,
    InvalidProposalRunsError,
    PlanProposed,
    Proposal,
    ProposalAlreadyExistsError,
)
from keeper.counsel.features.propose_plan.command import ProposePlan
from keeper.counsel.features.propose_plan.context import ProposePlanContext
from keeper.execution.aggregates.operation import OperationCannotBeCitedError
from keeper.shared.json_schema.validation import validate_values_against_schema


class _ParametersRejectedError(ValueError):
    """What the shared validator raises here, before the run is named.

    The validator constructs its error class from a reason alone, and the
    refusal this slice publishes also says which run the reason came from.
    So the reason is caught in this private shape and re-raised in the
    public one, which is how `define_procedure` names its step.
    """


def decide(
    state: Proposal | None,
    command: ProposePlan,
    *,
    context: ProposePlanContext,
    actor_id: UUID,
    now: datetime,
    new_id: UUID,
) -> list[PlanProposed]:
    """Decide the events produced by proposing a plan.

    Invariants:
      - State must be None, or the id already has a history
        -> ProposalAlreadyExistsError
      - The plan must put forward at least one run and at most
        `PROPOSAL_MAX_RUNS` -> InvalidProposalRunsError
      - No run may cite an operation that has been retired
        -> OperationCannotBeCitedError
      - Every run's values must satisfy the schema its operation declares
        -> InvalidProposalParametersError, naming the run

    The same checks `make_proposal` makes of its one run, made of every
    run, and any one failing refuses the whole plan: the runs were advised
    together, and running some of them is not what was advised. Every
    retirement is asked about before any values are, for the reason
    `define_procedure` gives: values checked against a routine nothing
    answers to tell the proposer nothing worth fixing.

    What is NOT checked here is anything that needs a beamline: whether a
    setup a run names is held, and whether a run may claim devices. A plan
    is made without a beamline, as every proposal is, so both are decided
    where it is adopted, which is where a beamline is chosen. That
    includes whether each operation's device use has been declared, which
    can change between proposing a plan and adopting it.
    """
    if state is not None:
        raise ProposalAlreadyExistsError(state.id)
    if not 1 <= len(command.runs) <= PROPOSAL_MAX_RUNS:
        msg = (
            f"A plan puts forward 1 to {PROPOSAL_MAX_RUNS} runs, and this one puts "
            f"forward {len(command.runs)}"
        )
        raise InvalidProposalRunsError(msg)
    for run in command.runs:
        operation = context.operations[run.operation_id]
        if operation.is_retired:
            raise OperationCannotBeCitedError(operation.id, operation.status)
    for index, run in enumerate(command.runs):
        try:
            validate_values_against_schema(
                run.parameters,
                context.operations[run.operation_id].parameters_schema,
                error_class=_ParametersRejectedError,
            )
        except _ParametersRejectedError as rejected:
            msg = f"Run {index} cannot run with these values: {rejected}"
            raise InvalidProposalParametersError(msg) from rejected
    return [
        PlanProposed(
            proposal_id=new_id,
            actor_id=actor_id,
            runs=command.runs,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
