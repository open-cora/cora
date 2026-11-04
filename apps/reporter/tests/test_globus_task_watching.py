"""What the two task watchers make of what their services say.

Both adapters take callables rather than clients, so everything here
runs without a network, a credential or an allocation.

The two cases worth reading are the ones where a service says the work
went fine and it did not: a transfer retrying a file that is not there,
and a reconstruction whose command exited non-zero. Those are the
mistakes these adapters exist to avoid.
"""

from __future__ import annotations

from typing import Any

import pytest

from reporter.adapters.globus_compute_tasks import GlobusComputeTasks
from reporter.adapters.globus_transfer_tasks import GlobusTransferTasks
from reporter.watching import Ending, UnknownWorkError


class _GoneError(Exception):
    """What a Globus client raises for a task it does not hold."""

    http_status = 404


def _transfer(task: dict[str, Any]) -> GlobusTransferTasks:
    return GlobusTransferTasks(get_task=lambda _: task)


def test_a_finished_transfer_is_reported_as_completed() -> None:
    assert _transfer({"status": "SUCCEEDED"}).ending("t") == Ending("Completed")


def test_a_transfer_the_service_failed_carries_the_fault_it_named() -> None:
    said = _transfer({"status": "FAILED", "nice_status": "PERMISSION_DENIED"}).ending("t")

    assert said is not None
    assert said.report == "Failed"
    assert "PERMISSION_DENIED" in said.detail


def test_a_transfer_retrying_a_file_that_is_not_there_is_failed_rather_than_waited_on() -> None:
    """Measured: Globus holds this ACTIVE and retries for a day."""
    said = _transfer({"status": "ACTIVE", "nice_status": "FILE_NOT_FOUND", "faults": 4}).ending("t")

    assert said is not None
    assert said.report == "Failed"
    assert "FILE_NOT_FOUND" in said.detail


def test_a_transfer_faulting_on_something_it_recovers_from_is_left_running() -> None:
    """A busy endpoint is a slow afternoon, not a broken transfer."""
    assert _transfer({"status": "ACTIVE", "nice_status": "ENDPOINT_TOO_BUSY"}).ending("t") is None


def test_a_transfer_still_moving_is_left_running() -> None:
    assert _transfer({"status": "ACTIVE", "nice_status": None}).ending("t") is None


def test_a_reference_this_service_never_held_says_so_rather_than_raising_its_own_error() -> None:
    """How a watcher learns to ask the other service instead."""

    def gone(_: str) -> Any:
        raise _GoneError

    with pytest.raises(UnknownWorkError):
        GlobusTransferTasks(get_task=gone).ending("t")


def _compute(task: dict[str, Any], result: Any = None) -> GlobusComputeTasks:
    return GlobusComputeTasks(get_task=lambda _: task, get_result=lambda _: result)


def test_a_reconstruction_whose_command_succeeded_is_reported_as_completed() -> None:
    said = _compute({"status": "success"}, {"returncode": 0}).ending("c")

    assert said == Ending("Completed")


def test_a_succeeded_task_whose_command_failed_is_not_reported_as_completed() -> None:
    """The service calls this successful. It produced nothing."""
    said = _compute(
        {"status": "success"},
        {"returncode": 1, "stderr": "tomocupy: no such dataset\n"},
    ).ending("c")

    assert said is not None
    assert said.report == "Failed"
    assert "no such dataset" in said.detail


def test_a_task_the_service_itself_failed_carries_the_exception_it_gave() -> None:
    said = _compute({"status": "failed", "exception": "worker died"}).ending("c")

    assert said is not None
    assert said.report == "Failed"
    assert "worker died" in said.detail


def test_a_reconstruction_still_queued_or_running_is_left_alone() -> None:
    assert _compute({"status": "waiting-for-ep"}).ending("c") is None
    assert _compute({"status": "running"}).ending("c") is None


def test_a_finished_task_whose_result_cannot_be_read_is_failed_rather_than_claimed() -> None:
    """Reporting completed would claim an outcome nothing has seen."""

    def gone(_: str) -> Any:
        raise RuntimeError("serializer refused")

    said = GlobusComputeTasks(get_task=lambda _: {"status": "success"}, get_result=gone).ending("c")

    assert said is not None
    assert said.report == "Failed"
