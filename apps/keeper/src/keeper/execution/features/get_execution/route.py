"""HTTP door for reading one execution.

`GET /executions/{execution_id}`, returning the execution and every step it holds. The
only read that returns the steps: a listing drops them, because they are
the largest thing an execution carries.

Every step carries a `setup`, which is an object holding a setup id and a
revision where dispatch pinned one and null where it did not. The key is
always present, null included. A reader follows the id and the revision
to the setup as it stood at that revision, which is what a conductor
applying one has to do, and a key that came and went with the value would
make every reader guess what its absence meant.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.execution import EngineState, ExecutionStatus, StepOutcome
from keeper.execution.features.get_execution.handler import Handler
from keeper.execution.features.get_execution.query import GetExecution
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_execution
    return handler


class PinnedSetupResponse(BaseModel):
    """The setup a step runs with, and the revision dispatch pinned.

    Read the values at `GET /setups/{setup_id}?revision=N`. The revision is
    the one that was latest when the execution was dispatched, so a later
    revision of the same setup is not what this step was asked to run.
    """

    setup_id: UUID
    revision: int


class ExecutionStepResponse(BaseModel):
    """One step, and whichever detail its outcome carried.

    `outcome` is null for a step nothing has reported yet, which is a
    different thing from a step that was skipped. Skipped means the execution
    reached the decision and passed it over; null means nothing was ever
    said, which is what a driver that died leaves behind.

    `procedure_step_id` names the composed step this one was dispatched
    from. Read the procedure to learn what the step was asked to do: the
    operation a run hands to an engine, the parameters it carries and
    the devices it declares are all there, and none of them should be
    recovered by taking `describes` apart.
    """

    step_id: UUID
    describes: str
    procedure_step_id: UUID
    outcome: StepOutcome | None
    engine_reference: str | None
    engine_state: EngineState | None
    cause: str | None
    setup: PinnedSetupResponse | None = Field(
        description="The setup and revision dispatch pinned this step to, or null where "
        "the step took no setup or the execution predates pinning."
    )


class GetExecutionResponse(BaseModel):
    """An execution as a reader sees it, steps and all."""

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: str
    status: ExecutionStatus
    steps: list[ExecutionStepResponse]


router = APIRouter(tags=["execution"])


@router.get(
    "/executions/{execution_id}",
    response_model=GetExecutionResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read executions.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No execution has that id.",
        },
    },
    summary="Read an execution",
)
async def get_execution(
    execution_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetExecutionResponse:
    execution = await handler(
        GetExecution(execution_id=execution_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetExecutionResponse(
        execution_id=execution.id,
        procedure_id=execution.procedure_id,
        procedure_name=execution.procedure_name.value,
        beamline=execution.beamline.value,
        status=execution.status,
        steps=[
            ExecutionStepResponse(
                step_id=step.id,
                describes=step.describes,
                procedure_step_id=step.procedure_step_id,
                outcome=step.outcome,
                engine_reference=step.engine_reference,
                engine_state=step.engine_state,
                cause=step.cause,
                setup=(
                    PinnedSetupResponse(setup_id=step.setup.setup_id, revision=step.setup.revision)
                    if step.setup is not None
                    else None
                ),
            )
            for step in execution.steps
        ],
    )
