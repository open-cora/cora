"""The Run aggregate: state, events, evolver, and its read path."""

from aroc.execution.aggregates.run.events import (
    RunEvent,
    RunReported,
    from_stored,
    to_payload,
)
from aroc.execution.aggregates.run.evolver import evolve, fold
from aroc.execution.aggregates.run.read import RUN_STREAM_TYPE, load_run
from aroc.execution.aggregates.run.state import (
    InvalidRunParametersError,
    Run,
    RunAlreadyExistsError,
    RunNotFoundError,
)

__all__ = [
    "RUN_STREAM_TYPE",
    "InvalidRunParametersError",
    "Run",
    "RunAlreadyExistsError",
    "RunEvent",
    "RunNotFoundError",
    "RunReported",
    "evolve",
    "fold",
    "from_stored",
    "load_run",
    "to_payload",
]
