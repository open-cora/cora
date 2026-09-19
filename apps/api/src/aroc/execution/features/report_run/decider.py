"""The decision: what reporting a run produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters, and the plan arrives on the context, precisely so this
function has nothing to fetch and nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.run import (
    InvalidRunParametersError,
    Run,
    RunAlreadyExistsError,
    RunReported,
)
from aroc.execution.features.report_run.command import ReportRun
from aroc.execution.features.report_run.context import ReportRunContext
from aroc.shared.json_schema.validation import validate_values_against_schema


def decide(
    state: Run | None,
    command: ReportRun,
    *,
    context: ReportRunContext,
    now: datetime,
    new_id: UUID,
) -> list[RunReported]:
    """Decide the events produced by reporting a run.

    Invariants:
      - State must be None, or the id already has a history
        -> RunAlreadyExistsError
      - The parameters must satisfy the plan's declared schema
        -> InvalidRunParametersError

    The handler has already refused a plan id with no stream behind it,
    so by the time the context is built the plan exists. Existence is the
    handler's to check and state is the decider's, which is the split
    docs/reference/patterns.md draws between a 404 and a refusal.

    `no_schema_message` is not passed, so the shared validator runs in
    its relaxed posture, and the choice does not matter here: a plan
    cannot be defined without a schema, so the absent-schema case the
    argument exists for cannot arise. Passing a message would be writing
    guidance for a state this context has already made unreachable.

    What is NOT checked is whether some other run already names this same
    external reference. Nothing here can see another stream, and closing
    that needs a cross-stream pattern rather than a rule in this
    function. See the Run state module for why the gap is left open and
    what closes it.
    """
    if state is not None:
        raise RunAlreadyExistsError(state.id)
    validate_values_against_schema(
        command.parameters,
        context.plan.parameters_schema,
        error_class=InvalidRunParametersError,
    )
    return [
        RunReported(
            run_id=new_id,
            plan_id=command.plan_id,
            parameters=command.parameters,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
