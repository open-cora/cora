"""Run the completion: authorize, load, decide, append.

Update-style. The command names a stream that already has rows, so the
shell loads and folds that history before deciding and appends at the
version it read.

All five commands that move an existing run share that shell, which lives
in `aroc.execution._run_update_handler` and is what this module binds.
What stays here is what is actually this slice's: the name it authorizes
under, the decision it makes, the shape it hands back, and a logger that
names this slice rather than the shared file.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution._run_update_handler import bind_run_update
from aroc.execution.features.complete_run.command import CompleteRun
from aroc.execution.features.complete_run.decider import decide
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "CompleteRun"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: CompleteRun,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""
    return bind_run_update(
        deps,
        command_name=_COMMAND_NAME,
        decide=decide,
        log=_log,
    )


__all__ = ["Handler", "bind"]
