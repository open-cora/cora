"""Asking Globus Transfer how a move it was given turned out.

One of the two services this facility hands long work to, and one of the
two `Watching` adapters that ask after it. They are separate modules
because they are separate systems: a reference belongs to exactly one of
them, and the other has never heard of it.

## Why a status is not an answer

Measured at this facility: a transfer whose source file does not exist
does not fail. The task sits in ACTIVE with `nice_status` FILE_NOT_FOUND
and the service retries it until the task's deadline, which is a day
after it was asked for. A watcher reading the status alone would poll
that for twenty-four hours and report nothing, which is indistinguishable
from a large file still moving.

So the fault is read as well, and one the service will never recover
from is reported as a failure. Which faults those are is this service's
vocabulary, which is why the set is here.

The same set exists on the driving side, in the engine that submits
these. That is a duplicate, and an uncomfortable one: two programs in
two repositories have to agree about which faults are fatal, and nothing
compares them. It is the price of each project being a repository that
stands alone, and it is written down here rather than discovered when
they drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from reporter.watching import Ending, UnknownWorkError

if TYPE_CHECKING:
    from collections.abc import Callable

SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
"""The two states this service stops a transfer in."""

HOPELESS: Final = frozenset(
    {
        "FILE_NOT_FOUND",
        "PERMISSION_DENIED",
        "NO_CREDENTIALS",
        "EXPIRED_CREDENTIALS",
        "AUTHENTICATION_FAILED",
        "ENDPOINT_NOT_FOUND",
        "QUOTA_EXCEEDED",
        "SUBJECT_ALT_NAME_MISMATCH",
    }
)
"""Faults that waiting will not cure, so waiting stops.

What is absent is as considered as what is here. A failed connection, a
busy endpoint and a paused one are all states a transfer recovers from,
and calling them failures would report a slow afternoon as a broken one.
"""

NOT_FOUND: Final = 404


@dataclass(frozen=True, slots=True)
class GlobusTransferTasks:
    """How one move turned out, over the Globus Transfer API.

    `get_task` is a callable rather than a client, so this is testable
    without a network and without a credential. What a deployment hands
    over is a bound method of its own client.
    """

    get_task: Callable[[str], Any]

    def ending(self, reference: str) -> Ending | None:
        task = self._task(reference)
        status = str(task.get("status") or "")
        fault = str(task.get("nice_status") or "")

        if status == SUCCEEDED:
            return Ending("Completed")
        if status == FAILED:
            return Ending("Failed", fault or "the service reported no reason")
        if fault in HOPELESS:
            return Ending("Failed", f"{fault} after {task.get('faults')} attempts")
        return None

    def _task(self, reference: str) -> Any:
        """The task document, or the news that this is not one of ours."""
        try:
            return self.get_task(reference)
        except Exception as asked:
            if getattr(asked, "http_status", None) == NOT_FOUND:
                raise UnknownWorkError(reference) from asked
            raise


__all__ = ["FAILED", "HOPELESS", "SUCCEEDED", "GlobusTransferTasks"]
