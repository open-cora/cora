"""The Run aggregate: state, events, evolver, and its read path."""

from aroc.execution.aggregates.run.events import (
    RunAborted,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunPaused,
    RunReported,
    RunResumed,
    from_stored,
    to_payload,
)
from aroc.execution.aggregates.run.evolver import evolve, fold
from aroc.execution.aggregates.run.instant import (
    InvalidOccurredAtError,
    normalize_occurred_at,
)
from aroc.execution.aggregates.run.read import (
    RUN_STREAM_TYPE,
    load_run,
    load_run_with_version,
)
from aroc.execution.aggregates.run.state import (
    InvalidRunParametersError,
    Run,
    RunAlreadyExistsError,
    RunCannotBeAbortedError,
    RunCannotBeCompletedError,
    RunCannotBeFailedError,
    RunCannotBePausedError,
    RunCannotBeResumedError,
    RunNotFoundError,
    RunStatus,
)

__all__ = [
    "RUN_STREAM_TYPE",
    "InvalidOccurredAtError",
    "InvalidRunParametersError",
    "Run",
    "RunAborted",
    "RunAlreadyExistsError",
    "RunCannotBeAbortedError",
    "RunCannotBeCompletedError",
    "RunCannotBeFailedError",
    "RunCannotBePausedError",
    "RunCannotBeResumedError",
    "RunCompleted",
    "RunEvent",
    "RunFailed",
    "RunNotFoundError",
    "RunPaused",
    "RunReported",
    "RunResumed",
    "RunStatus",
    "evolve",
    "fold",
    "from_stored",
    "load_run",
    "load_run_with_version",
    "normalize_occurred_at",
    "to_payload",
]
