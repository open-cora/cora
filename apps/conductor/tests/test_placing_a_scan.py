"""Where a collect step's data lands, worked out before anything reaches a server.

The rule is a function so it can be held to its refusals without a soft
IOC: the engine tests drive it against one, and these say what it accepts
and refuses in each clause.
"""

from __future__ import annotations

import pytest

from conductor.adapters.tomoscan_engine import PlacementRefusedError, placed_folder

PLACES = {"19-bm": "/data/cora/"}


def test_a_step_naming_no_place_lands_wherever_its_server_is_configured() -> None:
    assert placed_folder({"config": "smoke-19bm"}, PLACES) is None


def test_a_place_and_an_output_land_in_that_places_folder() -> None:
    folder = placed_folder({"at": "19-bm", "output": "runs/p7/r1/"}, PLACES)
    assert folder == "/data/cora/runs/p7/r1/"


@pytest.mark.parametrize("root", ["/data/cora", "/data/cora/"])
def test_a_places_folder_joins_the_same_with_or_without_its_trailing_slash(root: str) -> None:
    folder = placed_folder({"at": "19-bm", "output": "runs/p7/r1/"}, {"19-bm": root})
    assert folder == "/data/cora/runs/p7/r1/"


@pytest.mark.parametrize(
    ("step", "named"), [({"at": "19-bm"}, "'at'"), ({"output": "runs/p7/r1/"}, "'output'")]
)
def test_a_step_naming_only_one_half_is_refused(step: dict[str, object], named: str) -> None:
    with pytest.raises(PlacementRefusedError, match=f"names {named} and not"):
        placed_folder(step, PLACES)


def test_a_place_this_engine_was_not_given_is_refused_naming_the_ones_it_was() -> None:
    with pytest.raises(PlacementRefusedError, match="it holds 19-bm"):
        placed_folder({"at": "alcf", "output": "runs/p7/r1/"}, PLACES)


def test_an_engine_given_no_places_refuses_every_placement() -> None:
    with pytest.raises(PlacementRefusedError, match="it holds none"):
        placed_folder({"at": "19-bm", "output": "runs/p7/r1/"}, {})


def test_an_output_naming_a_file_is_refused_because_the_server_names_the_file() -> None:
    with pytest.raises(PlacementRefusedError, match="names a file"):
        placed_folder({"at": "19-bm", "output": "runs/p7/r1/scan.h5"}, PLACES)


@pytest.mark.parametrize("output", ["/runs/p7/", "../runs/", "runs/../../etc/", "runs//p7/"])
def test_an_output_that_could_leave_its_place_is_refused(output: str) -> None:
    with pytest.raises(PlacementRefusedError):
        placed_folder({"at": "19-bm", "output": output}, PLACES)


def test_a_refusal_before_anything_is_written_says_nothing_was_put_back() -> None:
    with pytest.raises(PlacementRefusedError) as refused:
        placed_folder({"at": "alcf", "output": "runs/"}, PLACES)
    assert not refused.value.restored
    assert str(refused.value).endswith("Nothing was written and no scan was started")
