"""Asking Globus Compute how a job it was given turned out.

The other of the two services this facility hands long work to. A
reconstruction runs for hours, far longer than the thing that submitted
it waited, so the record of how it went is owed by whatever asks later,
which is this.

## Why a succeeded task is not a succeeded reconstruction

The service reports whether it managed to run the command, which is not
whether the command worked. A reconstruction that started, read its
input and exited non-zero is a task the service calls successful.
Reporting that as completed would file a run that produced nothing as
one that produced something, and the record would carry an address
nobody can open.

So the returned mapping decides, not the status. The facility's own
wrapper draws the line the same way, calling a task ok only when the
result carries a zero return code, and this agrees with it deliberately
rather than by coincidence.

That judgement also exists on the driving side, in the engine that
submits these. Two programs in two repositories have to agree about it
and nothing compares them, which is the price of each project standing
alone as a repository. It is written down in both places rather than
left to be discovered when they drift.

## What a missing result is

A task the service has finished but whose payload it will not hand back
is a failure rather than a silence. Reporting it as still going would
poll it forever, and reporting it as completed would claim an outcome
nothing has seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from reporter.watching import Ending, UnknownWorkError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SUCCESS: Final = "success"
FAILURE: Final = "failed"
"""The two words this service stops a task in, in its own spelling."""


@dataclass(frozen=True, slots=True)
class GlobusComputeTasks:
    """How one reconstruction turned out, over the Globus Compute API.

    Two callables rather than a client, so this is testable without a
    network and without an allocation. A deployment hands over bound
    methods of its own.
    """

    get_task: Callable[[str], Any]
    get_result: Callable[[str], Any]

    def ending(self, reference: str) -> Ending | None:
        try:
            task: Any = self.get_task(reference)
        except Exception as asked:
            raise UnknownWorkError(reference) from asked

        status = str(task.get("status") or "").lower()
        if status not in (SUCCESS, FAILURE):
            return None
        if status == FAILURE:
            return Ending("Failed", str(task.get("exception") or "the service gave no reason"))

        result = self._result(reference)
        if not isinstance(result, dict):
            return Ending("Failed", f"the run returned {type(result).__name__} and not a result")
        said: Mapping[str, Any] = cast("Mapping[str, Any]", result)
        if said.get("returncode") == 0:
            return Ending("Completed")
        return Ending("Failed", _why(said))

    def _result(self, reference: str) -> Any:
        try:
            return self.get_result(reference)
        except Exception as asked:
            return f"nothing: {asked}"


def _why(result: Mapping[str, Any]) -> str:
    """The shortest honest account of a run that did not succeed."""
    said = str(result.get("error") or "")
    tail = str(result.get("stderr") or "").strip().splitlines()
    if tail:
        said = f"{said} {tail[-1]}" if said else tail[-1]
    code = result.get("returncode")
    return f"exited {code}: {said}".strip() if said else f"exited {code}"


__all__ = ["FAILURE", "SUCCESS", "GlobusComputeTasks"]
