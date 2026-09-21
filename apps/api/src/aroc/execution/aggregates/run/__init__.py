"""The Run aggregate: state, events, evolver, and its two read paths."""

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
from aroc.execution.aggregates.run.read import (
    RUN_STREAM_TYPE,
    load_run,
    load_run_with_version,
)
from aroc.execution.aggregates.run.state import (
    InvalidRunFilterError,
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
from aroc.execution.aggregates.run.summary import (
    RunSummary,
    RunSummaryLookup,
    RunSummaryPage,
)

__all__ = [
    "RUN_STREAM_TYPE",
    "InvalidRunFilterError",
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
    "RunSummary",
    "RunSummaryLookup",
    "RunSummaryPage",
    "evolve",
    "fold",
    "from_stored",
    "load_run",
    "load_run_with_version",
    "to_payload",
]
