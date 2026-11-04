"""What the compute engine does with a step, against a service that is a double.

The service is a stub because what is being checked is the seam: which
calls go out, what comes back as a run, and which of the ways a
reconstruction can fail to finish produces which outcome. Nothing here
needs a network, which is the point of the adapter importing nothing.

The case worth reading first is the one about a succeeded task whose
command exited non-zero. That is the distinction this adapter exists to
get right, and it is the one a compute service will not draw for you.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from conductor.adapters.globus_compute import (
    FAILED,
    SUCCEEDED,
    ComputeError,
    ComputeRefusedError,
    GlobusCompute,
    Said,
    UnknownRoutineError,
)
from conductor.seams import Citation, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Mapping

RECONSTRUCT = "reconstruct"


@dataclass
class _Service:
    """A compute service that reports whatever it was handed."""

    says: list[Said] = field(default_factory=lambda: [Said(SUCCEEDED)])
    submitted: list[tuple[str, dict[str, object], str | None]] = field(
        default_factory=list[tuple[str, dict[str, object], str | None]]
    )
    asked: list[str] = field(default_factory=list[str])

    def submit(
        self,
        *,
        source_path: str,
        settings: Mapping[str, object],
        label: str | None,
    ) -> str:
        self.submitted.append((source_path, dict(settings), label))
        return "task-1"

    def state(self, reference: str) -> Said:
        self.asked.append(reference)
        return self.says[min(len(self.asked), len(self.says)) - 1]


def _engine(service: _Service, **kwargs: object) -> GlobusCompute:
    return GlobusCompute(
        computes=service,
        routines=frozenset({RECONSTRUCT}),
        poll_interval=0.0,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_settled_reconstruction_is_reported_with_the_reference_the_far_side_gave() -> None:
    service = _Service()

    ran = _engine(service).run(RECONSTRUCT, {"source_path": "/eagle/a.h5"}, None)

    assert ran.engine_reference == "task-1"
    assert ran.said == SUCCEEDED


def test_a_task_that_succeeded_with_a_failing_command_is_refused_and_not_filed_as_done() -> None:
    """The distinction a compute service does not draw and this adapter must.

    A reconstruction that ran, read its input and exited non-zero is a
    task the service calls successful. Filing that as done would record
    an address nobody can open.
    """
    service = _Service(says=[Said(FAILED, "tomocupy exited 1: no such dataset")])

    with pytest.raises(ComputeRefusedError) as refused:
        _engine(service).run(RECONSTRUCT, {"source_path": "/eagle/a.h5"}, None)

    assert refused.value.reference == "task-1"
    assert "tomocupy exited 1" in str(refused.value)


def test_a_reconstruction_still_going_when_the_bound_runs_out_is_handed_off() -> None:
    """The ordinary outcome for work measured in hours, and not a failure."""
    service = _Service(says=[Said("running")])

    with pytest.raises(WorkHandedOffError) as handed:
        _engine(service, settle_timeout=0.0).run(RECONSTRUCT, {"source_path": "/eagle/a.h5"}, None)

    assert handed.value.reference == "task-1"


def test_a_step_naming_no_source_path_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(ComputeError):
        _engine(service).run(RECONSTRUCT, {}, None)

    assert service.submitted == []


def test_a_routine_this_engine_was_not_given_is_declined_rather_than_broken() -> None:
    service = _Service()

    with pytest.raises(UnknownRoutineError):
        _engine(service).run("tomography_scan", {"source_path": "/eagle/a.h5"}, None)

    assert service.submitted == []


def test_the_step_settings_reach_the_service_without_the_subject_among_them() -> None:
    """`source_path` is what to reconstruct, not an option to reconstruct it with."""
    service = _Service()

    _engine(service).run(
        RECONSTRUCT,
        {"source_path": "/eagle/a.h5", "rotation-axis": 1628.5, "energy": 92.0},
        None,
    )

    source_path, settings, _ = service.submitted[0]
    assert source_path == "/eagle/a.h5"
    assert settings == {"rotation-axis": 1628.5, "energy": 92.0}


def test_a_step_setting_overrides_the_deployments_default_for_that_setting() -> None:
    """The record says what was asked for, and a house setting is not an answer."""
    service = _Service()

    _engine(service, defaults={"rotation-axis": 1000.0, "energy": 92.0}).run(
        RECONSTRUCT,
        {"source_path": "/eagle/a.h5", "rotation-axis": 1628.5},
        None,
    )

    _, settings, _ = service.submitted[0]
    assert settings == {"rotation-axis": 1628.5, "energy": 92.0}


def test_a_citation_reaches_the_far_side_as_a_label_carrying_both_ids() -> None:
    service = _Service()

    _engine(service).run(
        RECONSTRUCT,
        {"source_path": "/eagle/a.h5"},
        Citation(execution_id="e-1", step_id="s-1"),
    )

    _, _, label = service.submitted[0]
    assert label is not None
    assert "e-1" in label
    assert "s-1" in label


def test_a_step_with_no_citation_attaches_no_label_rather_than_inventing_one() -> None:
    service = _Service()

    _engine(service).run(RECONSTRUCT, {"source_path": "/eagle/a.h5"}, None)

    _, _, label = service.submitted[0]
    assert label is None
