"""Moving data between named places, against a transfer service that is a double.

`GlobusMove` is what lets a chain of any length be one operation: a step
names a path and two places, and the engine resolves both places through
what a deployment installed. The cases below are the ways that could go
wrong without anything noticing.

A path that climbs out of its place would make a place's root no bound at
all. A route nobody installed would make the route list a suggestion. And
a hop that lands anywhere but the same relative path would leave the next
hop naming nothing, which is the property the chain test states directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from conductor.adapters.globus_move import (
    FAILED,
    SUCCEEDED,
    GlobusMove,
    Item,
    NoRouteError,
    PathRefusedError,
    Places,
    PlacesError,
    TransferRefusedError,
    UnknownRoutineError,
)
from conductor.seams import Citation, Said, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Sequence

MOVE = "move"
PLACES = (
    "19-bm=beamline-collection:/ alcf=alcf-collection:/imaging/19BM nersc=nersc-collection:/tomo"
)
ROUTES = "19-bm>alcf alcf>nersc nersc>19-bm alcf>19-bm"
"""Three places and four routes, with 19-bm>nersc deliberately absent."""


@dataclass
class _Service:
    """A transfer service that records what it was asked and reports what it was handed."""

    states: list[Said] = field(default_factory=lambda: [Said(SUCCEEDED)])
    submitted: list[tuple[str, str, tuple[Item, ...]]] = field(
        default_factory=list[tuple[str, str, tuple[Item, ...]]]
    )
    labels: list[str | None] = field(default_factory=list[str | None])

    def submit(
        self,
        *,
        source: str,
        destination: str,
        items: Sequence[Item],
        label: str | None,
    ) -> str:
        self.submitted.append((source, destination, tuple(items)))
        self.labels.append(label)
        return "task-1"

    def state(self, reference: str) -> Said:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def _mover(service: _Service) -> GlobusMove:
    return GlobusMove(
        transfers=service,
        routines=frozenset({MOVE}),
        places=Places.parse(PLACES, ROUTES),
        settle_timeout=0.05,
        poll_interval=0.0,
    )


def _step(
    path: object = "2026-2/sample_0004.h5", origin: object = "19-bm", destination: object = "alcf"
) -> dict[str, object]:
    return {"path": path, "from": origin, "to": destination}


def test_a_move_reads_from_the_origin_and_writes_the_same_path_under_the_destination() -> None:
    service = _Service()

    ran = _mover(service).run(MOVE, _step(), None)

    source, destination, items = service.submitted[0]
    assert (source, destination) == ("beamline-collection", "alcf-collection")
    assert items[0].source_path == "/2026-2/sample_0004.h5"
    assert items[0].destination_path == "/imaging/19BM/2026-2/sample_0004.h5"
    assert items[0].recursive is False
    assert ran.engine_reference == "task-1"
    assert ran.said == SUCCEEDED


def test_every_hop_of_a_chain_leaves_from_where_the_last_hop_landed() -> None:
    service = _Service()
    mover = _mover(service)

    for origin, destination in (("19-bm", "alcf"), ("alcf", "nersc"), ("nersc", "19-bm")):
        mover.run(MOVE, _step(origin=origin, destination=destination), None)

    left = [items[0].source_path for _, _, items in service.submitted]
    landed = [items[0].destination_path for _, _, items in service.submitted]
    assert left[1:] == landed[:-1]
    assert landed[-1] == left[0]


def test_a_path_ending_in_a_slash_moves_the_folder_and_everything_under_it() -> None:
    service = _Service()

    _mover(service).run(MOVE, _step("results/sample_0004_rec/", "alcf", "19-bm"), None)

    item = service.submitted[0][2][0]
    assert item.recursive is True
    assert item.source_path == "/imaging/19BM/results/sample_0004_rec/"
    assert item.destination_path == "/results/sample_0004_rec/"


def test_an_absolute_path_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(PathRefusedError, match="relative"):
        _mover(service).run(MOVE, _step(path="/2026-2/sample_0004.h5"), None)

    assert service.submitted == []


@pytest.mark.parametrize(
    "path",
    [
        "..",
        "../other/sample.h5",
        "2026-2/../../other/sample.h5",
        "2026-2/./sample.h5",
        "2026-2//sample.h5",
        "results//",
    ],
)
def test_a_path_with_an_empty_dot_or_parent_segment_is_refused_before_anything_is_submitted(
    path: str,
) -> None:
    service = _Service()

    with pytest.raises(PathRefusedError, match="outside its place"):
        _mover(service).run(MOVE, _step(path=path), None)

    assert service.submitted == []


@pytest.mark.parametrize("path", [None, "", "   "])
def test_a_step_naming_no_path_is_refused_before_anything_is_submitted(path: object) -> None:
    service = _Service()

    with pytest.raises(PathRefusedError, match="nothing to move"):
        _mover(service).run(MOVE, _step(path=path), None)

    assert service.submitted == []


def test_a_move_along_a_route_nobody_installed_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(NoRouteError, match="no route"):
        _mover(service).run(MOVE, _step(origin="19-bm", destination="nersc"), None)

    assert service.submitted == []


def test_a_place_this_engine_does_not_know_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(NoRouteError, match="not a place this engine knows"):
        _mover(service).run(MOVE, _step(destination="somewhere-else"), None)

    assert service.submitted == []


def test_a_move_naming_only_one_place_is_refused_before_anything_is_submitted() -> None:
    service = _Service()

    with pytest.raises(NoRouteError, match="names both"):
        _mover(service).run(MOVE, {"path": "2026-2/sample_0004.h5", "from": "19-bm"}, None)

    assert service.submitted == []


def test_a_step_cannot_name_a_collection_because_the_place_supplies_it() -> None:
    """A step that could name its own endpoints could move a beamline's
    data anywhere, and would read like any other step while doing it."""
    service = _Service()
    naming = {"source": "elsewhere", "destination": "elsewhere", "collection": "elsewhere"}

    _mover(service).run(MOVE, {**_step(), **naming}, None)

    source, destination, _ = service.submitted[0]
    assert (source, destination) == ("beamline-collection", "alcf-collection")


def test_a_routine_this_engine_was_not_told_about_is_declined() -> None:
    service = _Service()

    with pytest.raises(UnknownRoutineError):
        _mover(service).run("transfer", _step(), None)

    assert service.submitted == []


def test_a_move_still_going_when_the_bound_runs_out_is_handed_off() -> None:
    service = _Service(states=[Said("ACTIVE")])

    with pytest.raises(WorkHandedOffError) as handed:
        _mover(service).run(MOVE, _step(), None)

    assert handed.value.reference == "task-1"
    assert handed.value.routine == MOVE


def test_a_move_the_service_failed_raises_with_the_reason_the_far_side_gave() -> None:
    service = _Service(states=[Said(FAILED, "PERMISSION_DENIED after 1 attempts")])

    with pytest.raises(TransferRefusedError, match="PERMISSION_DENIED"):
        _mover(service).run(MOVE, _step(), None)


def test_a_move_that_settles_after_a_poll_or_two_is_still_a_run() -> None:
    service = _Service(states=[Said("ACTIVE"), Said("ACTIVE"), Said(SUCCEEDED)])
    mover = GlobusMove(
        transfers=service,
        routines=frozenset({MOVE}),
        places=Places.parse(PLACES, ROUTES),
        settle_timeout=5.0,
        poll_interval=0.0,
    )

    ran = mover.run(MOVE, _step(), None)

    assert ran.said == SUCCEEDED


def test_a_citation_travels_as_the_task_label() -> None:
    service = _Service()
    cites = Citation(execution_id="exec-1", step_id="step-1")

    _mover(service).run(MOVE, _step(), cites)

    label = service.labels[0]
    assert label is not None
    assert "exec-1" in label
    assert "step-1" in label


def test_no_citation_writes_no_label_rather_than_an_invented_one() -> None:
    service = _Service()

    _mover(service).run(MOVE, _step(), None)

    assert service.labels == [None]


def test_places_and_routes_are_read_from_their_two_settings() -> None:
    places = Places.parse(PLACES, ROUTES)

    assert sorted(places.known) == ["19-bm", "alcf", "nersc"]
    assert places.known["alcf"].collection == "alcf-collection"
    assert places.known["alcf"].root == "/imaging/19BM"
    assert ("alcf", "nersc") in places.routes
    assert ("19-bm", "nersc") not in places.routes


@pytest.mark.parametrize(
    ("places", "said"),
    [
        ("19-bm=beamline-collection alcf=a:/", "name=collection:root"),
        ("19-bm=:/ alcf=a:/", "name=collection:root"),
        ("19_BM=c:/ alcf=a:/", "not a place name"),
        ("19-bm=c:relative alcf=a:/", "not an absolute path"),
        ("19-bm=c:/ 19-bm=d:/ alcf=a:/", "listed twice"),
        ("", "no places"),
    ],
)
def test_a_place_setting_that_cannot_be_read_is_refused_when_the_engine_is_built(
    places: str, said: str
) -> None:
    with pytest.raises(PlacesError, match=said):
        Places.parse(places, "19-bm>alcf")


@pytest.mark.parametrize(
    ("routes", "said"),
    [
        ("19-bm>nersc", "not among the places"),
        ("19-bm>19-bm", "one place"),
        ("19-bm-alcf", "from>to"),
        ("", "no routes"),
    ],
)
def test_a_route_setting_that_cannot_be_read_is_refused_when_the_engine_is_built(
    routes: str, said: str
) -> None:
    with pytest.raises(PlacesError, match=said):
        Places.parse("19-bm=c:/ alcf=a:/", routes)
