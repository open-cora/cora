"""The Operation aggregate: state, events, evolver, and its two read paths."""

from keeper.execution.aggregates.operation.events import (
    OperationDefined,
    OperationDeviceUseDeclared,
    OperationEvent,
    OperationPlaceUseDeclared,
    OperationRetired,
    from_stored,
    to_payload,
)
from keeper.execution.aggregates.operation.evolver import evolve, fold
from keeper.execution.aggregates.operation.read import (
    OPERATION_STREAM_TYPE,
    load_operation,
    load_operation_with_version,
)
from keeper.execution.aggregates.operation.state import (
    OPERATION_NAME_MAX_LENGTH,
    InvalidOperationNameError,
    InvalidOperationParametersSchemaError,
    InvalidOperationPlaceUseError,
    Operation,
    OperationAlreadyExistsError,
    OperationCannotBeCitedError,
    OperationCannotBeComposedError,
    OperationCannotBeRetiredError,
    OperationDeviceUseCannotBeDeclaredError,
    OperationName,
    OperationNotFoundError,
    OperationPlaceUseCannotBeDeclaredError,
    OperationStatus,
    PlaceUse,
)
from keeper.execution.aggregates.operation.summary import (
    OperationSummary,
    OperationSummaryLookup,
    OperationSummaryPage,
)

__all__ = [
    "OPERATION_NAME_MAX_LENGTH",
    "OPERATION_STREAM_TYPE",
    "InvalidOperationNameError",
    "InvalidOperationParametersSchemaError",
    "InvalidOperationPlaceUseError",
    "Operation",
    "OperationAlreadyExistsError",
    "OperationCannotBeCitedError",
    "OperationCannotBeComposedError",
    "OperationCannotBeRetiredError",
    "OperationDefined",
    "OperationDeviceUseCannotBeDeclaredError",
    "OperationDeviceUseDeclared",
    "OperationEvent",
    "OperationName",
    "OperationNotFoundError",
    "OperationPlaceUseCannotBeDeclaredError",
    "OperationPlaceUseDeclared",
    "OperationRetired",
    "OperationStatus",
    "OperationSummary",
    "OperationSummaryLookup",
    "OperationSummaryPage",
    "PlaceUse",
    "evolve",
    "fold",
    "from_stored",
    "load_operation",
    "load_operation_with_version",
    "to_payload",
]
