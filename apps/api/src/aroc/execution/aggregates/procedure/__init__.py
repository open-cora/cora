"""The Procedure aggregate: a routine this system composed, and its steps."""

from aroc.execution.aggregates.procedure.events import (
    ProcedureDefined,
    ProcedureEvent,
    from_stored,
    to_payload,
)
from aroc.execution.aggregates.procedure.evolver import evolve, fold
from aroc.execution.aggregates.procedure.read import PROCEDURE_STREAM_TYPE, load_procedure
from aroc.execution.aggregates.procedure.state import (
    PROCEDURE_MAX_SCOPES_PER_STEP,
    PROCEDURE_MAX_STEPS,
    PROCEDURE_NAME_MAX_LENGTH,
    PROCEDURE_RECORD_MAX_LENGTH,
    PROCEDURE_SCOPE_MAX_LENGTH,
    AcquireStep,
    InvalidProcedureNameError,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
    MoveStep,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureName,
    ProcedureNotFoundError,
    ProcedureStep,
    describes,
    validated_steps,
)
from aroc.execution.aggregates.procedure.summary import (
    ProcedureSummary,
    ProcedureSummaryLookup,
    ProcedureSummaryPage,
)

__all__ = [
    "PROCEDURE_MAX_SCOPES_PER_STEP",
    "PROCEDURE_MAX_STEPS",
    "PROCEDURE_NAME_MAX_LENGTH",
    "PROCEDURE_RECORD_MAX_LENGTH",
    "PROCEDURE_SCOPE_MAX_LENGTH",
    "PROCEDURE_STREAM_TYPE",
    "AcquireStep",
    "InvalidProcedureNameError",
    "InvalidProcedureParametersError",
    "InvalidProcedureStepsError",
    "MoveStep",
    "Procedure",
    "ProcedureAlreadyExistsError",
    "ProcedureDefined",
    "ProcedureEvent",
    "ProcedureName",
    "ProcedureNotFoundError",
    "ProcedureStep",
    "ProcedureSummary",
    "ProcedureSummaryLookup",
    "ProcedureSummaryPage",
    "describes",
    "evolve",
    "fold",
    "from_stored",
    "load_procedure",
    "to_payload",
    "validated_steps",
]
