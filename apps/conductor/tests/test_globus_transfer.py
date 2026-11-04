"""What the transfer engine does with a step, against a service that is a double.

The service is a stub because what is being checked is the seam: which
calls go out, what comes back as a run, and which of the two ways a
transfer can fail to finish produces which outcome. Nothing here needs a
network, which is the point of the adapter importing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from conductor.adapters.globus_transfer import (
    FAILED,
    SUCCEEDED,
    GlobusTransfer,
    Item,
    TransferError,
    TransferRefusedError,
    UnknownRoutineError,
)
from conductor.seams import Citation, Said, WorkHandedOffError

MOVE = "globus_transfer"


@dataclass
class _Service:
    """A transfer service that reports whatever states it was handed."""

    states: list[Said] = field(default_factory=lambda: [Said(SUCCEEDED)])
    submitted: list[tuple[str, str, tuple[Item, ...], str | None]] = field(
        default_factory=list[tuple[str, str, tuple[Item, ...], str | None]]
    )

    def submit(
        self,
        *,
        source: str,
        destination: str,
        items: tuple[Item, ...],
        label: str | None,
    ) -> str:
        self.submitted.append((source, destination, tuple(items), label))
        return "task-1"

    def state(self, reference: str) -> Said:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def _engine(service: _Service, **over: object) -> GlobusTransfer:
    settings: dict[str, object] = {
        "transfers": service,
        "routines": frozenset({MOVE}),
        "source": "beamline-collection",
        "destination": "alcf-collection",
        "destination_prefix": "/eagle/imaging/19BM/data",
        "settle_timeout": 0.05,
        "poll_interval": 0.0,
    }
    settings.update(over)
    return GlobusTransfer(**settings)  # pyright: ignore[reportArgumentType]


def test_a_finished_transfer_comes_back_as_a_run_naming_the_task() -> None:
    service = _Service()

    ran = _engine(service).run(MOVE, {"source_path": "/data/scan_045.h5"}, None)

    assert ran.engine_reference == "task-1"
    assert ran.said == SUCCEEDED


def test_a_file_lands_under_the_configured_prefix_keeping_its_own_name() -> None:
    service = _Service()

    _engine(service).run(MOVE, {"source_path": "/gdata/19BM/raw/scan_045.h5"}, None)

    _, _, items, _ = service.submitted[0]
    assert items[0].destination_path == "/eagle/imaging/19BM/data/scan_045.h5"


def test_the_collections_come_from_the_deployment_and_not_from_the_step() -> None:
    """A step that could name its own endpoints could move a beamline's
    data anywhere, and would read like any other step while doing it."""
    service = _Service()

    _engine(service).run(
        MOVE,
        {"source_path": "/data/s.h5", "source": "somewhere-else", "destination": "elsewhere"},
        None,
    )

    source, destination, _, _ = service.submitted[0]
    assert (source, destination) == ("beamline-collection", "alcf-collection")


def test_a_refusal_carries_the_reason_the_far_side_gave_and_not_just_the_state() -> None:
    """Measured: a transfer fails for reasons a person can act on.

    A missing source and a permission are different problems with
    different fixes, and a task id alone sends whoever reads the record
    to a web console to learn which one it was.
    """
    service = _Service(states=[Said(FAILED, "FILE_NOT_FOUND after 4 attempts")])

    with pytest.raises(TransferRefusedError) as refused:
        _engine(service).run(MOVE, {"source_path": "/data/a.h5"}, None)

    assert "FILE_NOT_FOUND" in str(refused.value)
    assert refused.value.reference == "task-1"


def test_a_transfer_still_going_when_the_bound_runs_out_is_handed_off() -> None:
    service = _Service(states=[Said("ACTIVE")])

    with pytest.raises(WorkHandedOffError) as handed:
        _engine(service).run(MOVE, {"source_path": "/data/s.h5"}, None)

    assert handed.value.reference == "task-1"
    assert handed.value.routine == MOVE


def test_a_transfer_the_service_failed_raises_rather_than_handing_off() -> None:
    """The far side finished and said no, which is nothing for a watcher
    to resolve later."""
    service = _Service(states=[Said(FAILED, "FILE_NOT_FOUND after 4 attempts")])

    with pytest.raises(TransferRefusedError):
        _engine(service).run(MOVE, {"source_path": "/data/s.h5"}, None)


def test_a_transfer_that_settles_after_a_poll_or_two_is_still_a_run() -> None:
    service = _Service(states=[Said("ACTIVE"), Said("ACTIVE"), Said(SUCCEEDED)])

    ran = _engine(service, settle_timeout=5.0).run(MOVE, {"source_path": "/data/s.h5"}, None)

    assert ran.said == SUCCEEDED


def test_a_citation_travels_as_the_task_label() -> None:
    service = _Service()
    cites = Citation(execution_id="exec-1", step_id="step-1")

    _engine(service).run(MOVE, {"source_path": "/data/s.h5"}, cites)

    _, _, _, label = service.submitted[0]
    assert label is not None
    assert "exec-1" in label
    assert "step-1" in label


def test_no_citation_writes_no_label_rather_than_an_invented_one() -> None:
    service = _Service()

    _engine(service).run(MOVE, {"source_path": "/data/s.h5"}, None)

    _, _, _, label = service.submitted[0]
    assert label is None


def test_a_step_naming_no_source_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(TransferError, match="source_path"):
        _engine(service).run(MOVE, {}, None)

    assert service.submitted == []


def test_a_routine_this_engine_was_not_told_about_is_declined() -> None:
    service = _Service()

    with pytest.raises(UnknownRoutineError):
        _engine(service).run("tomography_scan", {"source_path": "/data/s.h5"}, None)

    assert service.submitted == []
