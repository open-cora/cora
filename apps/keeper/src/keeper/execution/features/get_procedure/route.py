"""HTTP door for reading a procedure.

`GET /procedures/{procedure_id}`. Returns the id, the name, every step in
order, and whether it has been retired, which is the whole of what a
procedure is.

This is the only read that returns the steps. A listing drops them,
because a procedure may hold a thousand and a page of fifty would be
almost entirely steps.

Parameters go back exactly as they were stored, not re-rendered. A caller
comparing what an engine was given against what was composed has to be
working from the record rather than from a rendering of it.

The state is folded from the stream on every call, and a retired
procedure reads back like any other, with its status saying so. Retiring
is not deleting: an execution that cites one of its steps still reaches
the step it ran.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.procedure import ComposedStep, ProcedureStatus, SetStep
from keeper.execution.features.get_procedure.handler import Handler
from keeper.execution.features.get_procedure.query import GetProcedure
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class SetStepResponse(BaseModel):
    """A step that sends one record to one value."""

    kind: Literal["set"] = "set"
    step_id: UUID
    record: str
    to: float


class RunStepResponse(BaseModel):
    """A step that asks an engine to run an operation."""

    kind: Literal["run"] = "run"
    step_id: UUID
    operation_id: UUID
    parameters: dict[str, Any]
    scopes: list[str]
    drives_no_device: bool


StepResponse = Annotated[SetStepResponse | RunStepResponse, Field(discriminator="kind")]


class GetProcedureResponse(BaseModel):
    """A procedure as this system currently holds it."""

    procedure_id: UUID
    name: str
    beamline: str
    steps: list[StepResponse]
    status: ProcedureStatus = Field(
        description="Active, or Retired: a dispatch of a retired procedure is refused."
    )


def to_response_step(composed: ComposedStep) -> SetStepResponse | RunStepResponse:
    """Render one stored step for a reader, under the id it was composed with.

    `step_id` is what an execution's step cites, so it is what a reader
    comparing a traversal against the routine it came from joins on.
    """
    step = composed.step
    if isinstance(step, SetStep):
        return SetStepResponse(step_id=composed.id, record=step.record, to=step.to)
    return RunStepResponse(
        step_id=composed.id,
        operation_id=step.operation_id,
        parameters=step.parameters,
        scopes=list(step.scopes),
        drives_no_device=step.drives_no_device,
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_procedure
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/procedures/{procedure_id}",
    response_model=GetProcedureResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read procedures.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No procedure has that id.",
        },
    },
    summary="Read a procedure",
)
async def get_procedure(
    procedure_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetProcedureResponse:
    procedure = await handler(
        GetProcedure(procedure_id=procedure_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetProcedureResponse(
        procedure_id=procedure.id,
        name=procedure.name.value,
        beamline=procedure.beamline.value,
        steps=[to_response_step(composed) for composed in procedure.steps],
        status=procedure.status,
    )
