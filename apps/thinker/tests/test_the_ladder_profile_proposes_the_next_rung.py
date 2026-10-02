"""The profile that can put work forward, and the rungs it climbs.

`infra/thinking/ladder.py` is the first thing in this repository that
reaches `Propose`, so it is the first whose output can become a run at a
beamline. It sits outside `src`, loaded by a dotted path rather than
imported, so nothing else here would notice it breaking.

Cases are built in this file rather than taken from the shared builder,
because that one composes steps that set a record and this strategy
reads steps that ask an engine to run. A ladder tested against set steps
would abstain on every one of them and pass while climbing nothing.

Loaded through the entrypoint's own loader for the reason the sibling
profile's suite gives: the dotted path, the attribute lookup and the
call are what a deployment depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from thinker.__main__ import concluding_for
from thinker.case import Case, Outcome, Step
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.config import ThinkerConfig

if TYPE_CHECKING:
    from thinker.seams import Concluding

THINKING = Path(__file__).resolve().parents[1] / "infra" / "thinking"
PROFILE = "ladder:inference"

OPERATION = "01a0f82d-21ef-7050-b28f-5251a1e83f5b"
"""An operation id in the shape the record writes them."""


def _loaded() -> Concluding:
    sys.path.insert(0, str(THINKING))
    try:
        return concluding_for(
            ThinkerConfig(base_url="https://keeper.example", token="t", inference_profile=PROFILE)
        )
    finally:
        sys.path.remove(str(THINKING))


@pytest.fixture(name="thinking")
def _thinking() -> Concluding:
    return _loaded()


def _run_step(
    *,
    index: int = 0,
    angles: object = 8,
    outcome: Outcome | None = None,
    kind: str = "run",
) -> Step:
    parameters: dict[str, Any] = {"ExposureTime": 0.05}
    if angles is not None:
        parameters["NumAngles"] = angles
    return Step(
        index=index,
        step_id=f"step-{index}",
        asked={"kind": kind, "operation_id": OPERATION, "parameters": parameters},
        became=outcome if outcome is not None else Outcome("Done", "Completed", None),
    )


def _case(*steps: Step, ended: bool = True, objective: str | None = "resolve the edge") -> Case:
    return Case(
        execution_id="exec-1",
        procedure="sim scan 19-bm",
        steps=steps,
        ended=ended,
        objective=objective,
    )


def test_the_shipped_profile_loads_by_the_dotted_path_a_deployment_writes() -> None:
    assert _loaded() is not None


def test_a_clean_run_below_the_ceiling_asks_for_the_same_run_at_the_next_rung(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(_case(_run_step(angles=8)))

    assert isinstance(said, Propose)
    assert said.operation_id == OPERATION
    assert said.parameters["NumAngles"] == 16


def test_a_proposal_carries_the_other_parameters_through_unchanged(
    thinking: Concluding,
) -> None:
    """Only the rung moves.

    A strategy that rebuilt the parameters would drop whatever it did
    not know about, and the keeper would accept the result because the
    schema makes those optional.
    """
    said = thinking.conclude(_case(_run_step(angles=8)))

    assert isinstance(said, Propose)
    assert said.parameters["ExposureTime"] == 0.05


def test_the_rung_never_steps_past_the_ceiling(thinking: Concluding) -> None:
    said = thinking.conclude(_case(_run_step(angles=48)))

    assert isinstance(said, Propose)
    assert said.parameters["NumAngles"] == 64


def test_a_run_already_at_the_ceiling_is_the_objective_met(thinking: Concluding) -> None:
    said = thinking.conclude(_case(_run_step(angles=64)))

    assert isinstance(said, Stop)


def test_a_run_at_the_ceiling_with_no_objective_cannot_be_called_enough(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(_case(_run_step(angles=64), objective=None))

    assert isinstance(said, Abstain)


def test_a_broken_run_is_not_climbed_from(thinking: Concluding) -> None:
    broken = Outcome("Broken", None, "TimeoutError")
    said = thinking.conclude(_case(_run_step(angles=8, outcome=broken)))

    assert isinstance(said, Refer)


def test_a_run_reported_done_whose_engine_failed_is_not_climbed_from(
    thinking: Concluding,
) -> None:
    """The disagreement both profiles have to read the same way.

    Climbing here would ask for twice as much of something that did not
    work, which is the one way this strategy could do harm inside an
    authorization that permits it to run.
    """
    failed = Outcome("Done", "Failed", None)
    said = thinking.conclude(_case(_run_step(angles=8, outcome=failed)))

    assert isinstance(said, Refer)


def test_a_finished_run_is_climbed_from_even_though_its_execution_is_still_open(
    thinking: Concluding,
) -> None:
    """A round may be opened on an execution that has not been closed.

    The step reported and nothing faulted, so there is a rung to read.
    Waiting for the execution to close as well would mean a pursuit
    could never turn until something else ended it.
    """
    said = thinking.conclude(_case(_run_step(angles=8), ended=False))

    assert isinstance(said, Propose)
    assert said.parameters["NumAngles"] == 16


def test_a_step_that_never_reported_and_is_still_open_is_not_climbed_from(
    thinking: Concluding,
) -> None:
    unreported = Step(index=0, step_id="step-0", asked={"kind": "run"}, became=None)
    said = thinking.conclude(_case(unreported, ended=False))

    assert isinstance(said, Abstain)


def test_a_procedure_that_only_sets_records_has_no_run_to_ask_for_again(
    thinking: Concluding,
) -> None:
    said = thinking.conclude(_case(_run_step(angles=8, kind="set")))

    assert isinstance(said, Abstain)


def test_a_run_whose_rung_is_missing_is_not_guessed_at(thinking: Concluding) -> None:
    said = thinking.conclude(_case(_run_step(angles=None)))

    assert isinstance(said, Abstain)


def test_a_run_whose_rung_is_not_a_whole_number_is_not_stepped(thinking: Concluding) -> None:
    said = thinking.conclude(_case(_run_step(angles=8.5)))

    assert isinstance(said, Abstain)


def test_a_rung_carrying_a_boolean_is_not_treated_as_a_number(thinking: Concluding) -> None:
    """`True` is an `int` in Python, and doubling it proposes two angles."""
    said = thinking.conclude(_case(_run_step(angles=True)))

    assert isinstance(said, Abstain)


def test_the_ladder_reaches_the_ceiling_in_a_handful_of_turns(thinking: Concluding) -> None:
    """The property that makes this watchable, asserted rather than assumed.

    A strategy that added one would need fifty six turns from eight, and
    a demonstration nobody stays for proves nothing to anybody.
    """
    angles, turns = 8, 0
    said: Conclusion = thinking.conclude(_case(_run_step(angles=angles)))
    while isinstance(said, Propose) and turns < 20:
        angles = said.parameters["NumAngles"]
        turns += 1
        said = thinking.conclude(_case(_run_step(angles=angles)))

    assert isinstance(said, Stop), f"never reached the ceiling, stopped at {said}"
    assert turns <= 5, f"took {turns} turns to reach the ceiling, which is too many to watch"
