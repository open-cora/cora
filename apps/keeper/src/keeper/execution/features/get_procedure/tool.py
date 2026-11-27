"""MCP door for reading a procedure.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The step models are declared again here rather than imported from the
route, for the reason `define_procedure/tool.py` gives: the two surfaces
share a handler and not a boundary.
"""

from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.execution.aggregates.procedure import ComposedStep, ProcedureStatus, SetStep
from keeper.execution.features.get_procedure.handler import Handler
from keeper.execution.features.get_procedure.query import GetProcedure
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class SetStepOutput(BaseModel):
    """A step that sends one record to one value."""

    kind: Literal["set"] = "set"
    step_id: UUID
    record: str
    to: float


class RunStepOutput(BaseModel):
    """A step that asks an engine to run an operation.

    `drives_no_device` is here as it is on the route. A run composed for a
    plan claims nothing when its operation is declared to drive nothing,
    and an agent reading the procedure over this surface has to be able to
    tell that step from one whose devices were simply left off.
    """

    kind: Literal["run"] = "run"
    step_id: UUID
    operation_id: UUID
    parameters: dict[str, Any]
    scopes: list[str]
    drives_no_device: bool


StepOutput = Annotated[SetStepOutput | RunStepOutput, Field(discriminator="kind")]


class GetProcedureOutput(BaseModel):
    """A procedure as this system currently holds it."""

    procedure_id: UUID
    name: str
    beamline: str
    steps: list[StepOutput]
    status: ProcedureStatus


def _to_output_step(composed: ComposedStep) -> SetStepOutput | RunStepOutput:
    """Render one stored step for a reader, under the id it was composed with.

    `step_id` is what an execution's step cites, so it is what a reader
    comparing a traversal against the routine it came from joins on.
    """
    step = composed.step
    if isinstance(step, SetStep):
        return SetStepOutput(step_id=composed.id, record=step.record, to=step.to)
    return RunStepOutput(
        step_id=composed.id,
        operation_id=step.operation_id,
        parameters=step.parameters,
        scopes=list(step.scopes),
        drives_no_device=step.drives_no_device,
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_procedure",
        description=(
            "Read a procedure by id: the name it was composed under, every "
            "step it runs, in order, and whether it has been retired, in which "
            "case a dispatch of it is refused."
        ),
    )
    async def get_procedure_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID,
    ) -> GetProcedureOutput:
        handler = get_handler()
        procedure = await handler(
            GetProcedure(procedure_id=procedure_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetProcedureOutput(
            procedure_id=procedure.id,
            name=procedure.name.value,
            beamline=procedure.beamline.value,
            steps=[_to_output_step(composed) for composed in procedure.steps],
            status=procedure.status,
        )
