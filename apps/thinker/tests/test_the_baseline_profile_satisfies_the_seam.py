"""The profile this repository ships loads and answers every branch.

`infra/thinking/baseline.py` is what `inference.profile` can name without a
site writing anything, so it is the one thing standing between an installed
thinker and a thinker that will not start. It sits outside `src`, where
pyright does not reach and no other test looks, and it is loaded by a dotted
path rather than imported, so nothing else here would notice it breaking.

The loading test goes through `concluding_for` rather than importing the
module, because the dotted path, the attribute lookup and the call that the
entrypoint performs are the part a deployment depends on and the part a
rename breaks. Importing it directly would pass against a profile the
installer could not load.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests._fakes import RecordingKeeper, a_case
from thinker.__main__ import concluding_for
from thinker.case import Outcome
from thinker.conclusions import Abstain, Refer, Stop
from thinker.config import ThinkerConfig

if TYPE_CHECKING:
    from thinker.seams import Concluding

THINKING = Path(__file__).resolve().parents[1] / "infra" / "thinking"
"""Where the shipped profile sits, which the unit puts on `PYTHONPATH`."""

PROFILE = "baseline:inference"
"""The dotted path a deployment writes, spelled as the unit spells it."""


def _loaded() -> Concluding:
    """The seam, through the entrypoint's own loader and off sys.path again."""
    sys.path.insert(0, str(THINKING))
    try:
        return concluding_for(
            ThinkerConfig(base_url="https://keeper.example", token="t", inference_profile=PROFILE),
            looking=RecordingKeeper(),
        )
    finally:
        sys.path.remove(str(THINKING))


@pytest.fixture(name="thinking")
def _thinking() -> Concluding:
    return _loaded()


def test_the_shipped_profile_loads_by_the_dotted_path_a_deployment_writes() -> None:
    assert _loaded() is not None


def test_a_run_whose_every_step_is_done_against_an_objective_is_enough(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", "Done"), objective="find the edge"))
    assert isinstance(said, Stop)


def test_a_clean_run_nobody_set_an_objective_for_cannot_be_called_enough(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", "Done"), objective=None))
    assert isinstance(said, Abstain)


def test_a_step_whose_driver_raised_sends_somebody_to_the_record(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", "Broken"), objective="find the edge"))
    assert isinstance(said, Refer)


def test_a_step_reported_done_whose_engine_failed_is_not_a_run_that_worked(
    thinking: Concluding,
) -> None:
    """The disagreement `thinker.case` keeps both words for.

    A table reading only the driver's word concludes the objective was met
    on a run whose engine failed, which is the one way this profile could
    be confidently wrong rather than merely unhelpful.
    """
    failed = Outcome(reported="Done", engine_state="Failed", cause=None)
    said = thinking.conclude(a_case(became=("Done", failed), objective="find the edge"))
    assert isinstance(said, Refer)


def test_a_step_reported_done_whose_engine_aborted_is_not_a_run_that_worked(
    thinking: Concluding,
) -> None:
    aborted = Outcome(reported="Done", engine_state="Aborted", cause=None)
    said = thinking.conclude(a_case(became=("Done", aborted), objective="find the edge"))
    assert isinstance(said, Refer)


def test_a_step_that_set_a_record_and_opened_no_run_is_not_read_as_a_fault(
    thinking: Concluding,
) -> None:
    """A set carries no engine state, and `None` is not a failing word."""
    a_set = Outcome(reported="Done", engine_state=None, cause=None)
    said = thinking.conclude(a_case(became=(a_set, a_set), objective="find the edge"))
    assert isinstance(said, Stop)


def test_an_execution_still_open_with_steps_to_come_has_nothing_to_conclude_yet(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", None), ended=False, objective="find the edge"))
    assert isinstance(said, Abstain)


def test_an_execution_closed_with_steps_it_never_reached_sends_somebody_to_the_record(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", None), ended=True, objective="find the edge"))
    assert isinstance(said, Refer)


def test_a_procedure_whose_steps_were_all_skipped_is_not_an_objective_met(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Skipped", "Skipped"), objective="find the edge"))
    assert isinstance(said, Abstain)


def test_a_step_refused_before_it_started_is_not_an_objective_met(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(a_case(became=("Done", "Refused"), objective="find the edge"))
    assert isinstance(said, Abstain)


def test_an_execution_with_no_steps_at_all_concludes_nothing(thinking: Concluding) -> None:
    said = thinking.conclude(a_case(became=(), objective="find the edge"))
    assert isinstance(said, Abstain)


def test_nothing_this_profile_concludes_can_become_work_at_a_beamline(
    thinking: Concluding,
) -> None:
    """The property the whole file exists to hold.

    Every case the suite above builds, asserted once more against the one
    conclusion this profile is not allowed to reach. A rule added later
    that proposes a re-run would pass every test above and fail here.
    """
    failed = Outcome(reported="Done", engine_state="Failed", cause=None)
    everything = [
        a_case(became=("Done", "Done"), objective="find the edge"),
        a_case(became=("Done", "Done"), objective=None),
        a_case(became=("Done", "Broken"), objective="find the edge"),
        a_case(became=("Done", failed), objective="find the edge"),
        a_case(became=("Done", None), ended=False, objective="find the edge"),
        a_case(became=("Done", None), ended=True, objective="find the edge"),
        a_case(became=("Skipped", "Skipped"), objective="find the edge"),
        a_case(became=(), objective="find the edge"),
    ]
    reached = {type(thinking.conclude(case)).__name__ for case in everything}
    assert reached <= {"Stop", "Abstain", "Refer"}, (
        f"This profile is advisory and reached {sorted(reached)}. A profile that "
        "proposes is a different file behind the same dotted path."
    )
