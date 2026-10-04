"""A thinking that asks for the same run again with one value raised.

The second profile, and the first that can put work forward. Where the
advisory one reads a case and reports, this one answers a clean run by
proposing the run it just read with a single parameter stepped, until a
rule says the goal is met.

Deterministic on purpose. It is the baseline a model has to beat, and
keeping a model out of the first turning means what is being tested is
the machinery rather than anybody's judgement.

## The ladder

```
    any step broken, or an engine that aborted or failed  ->  Refer
    the execution ended with steps it never reached       ->  Refer
    steps not reached and the execution still open        ->  Abstain
    nothing here that asked an engine to run              ->  Abstain
    the rung is already at the ceiling                    ->  Stop
    otherwise                                             ->  Propose, rung doubled
```

Doubling rather than adding, so a run reaches the ceiling in a handful
of turns and a demonstration ends while somebody is still watching it.

## Why proposing is safe to do deterministically

A proposal is a record and nothing more. Turning one into work takes a
second act by somebody else, who has to state the beamline it runs at
and the devices it may drive, and those are refused unless a standing
authorization already covers them. So a profile that proposes on every
clean run cannot run anything by itself, and inside an authorization
that bounds how many times the loop may turn, it cannot run away either.

What this profile must not do is propose something that could not have
worked. The keeper refuses a proposal whose parameters fail the
operation's schema, and that refusal is deliberately not swallowed, so
a rung that steps out of range is an error rather than a row.

## Why the rung is named here and not configured

It is a property of the strategy rather than of the deployment. A
different instrument wants a different rung and a different ceiling,
and that is a different file behind the same dotted path, which is what
the inference seam is for. A setting here would be a thinker holding an
opinion about an operation it is built not to know about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

from outcomes import DONE, ended_badly, faulted

from thinker.conclusions import Abstain, Propose, Refer, Stop

if TYPE_CHECKING:
    from collections.abc import Mapping

    from thinker.case import Case, Step
    from thinker.conclusions import Conclusion
    from thinker.seams import Concluding, Looking

RUN: Final = "run"
"""What the record calls a step that asks an engine to run something."""

RUNG: Final = "NumAngles"
"""The parameter this ladder climbs."""

CEILING: Final = 64
"""The rung at which this strategy calls the goal met.

A number rather than a reading of the data, because nothing here looks
at what was collected. That is the honest limit of a deterministic
strategy and the reason one exists only to be beaten.
"""


def _rungs(case: Case) -> list[tuple[Step, Mapping[str, Any]]]:
    """Every step that asked an engine to run, with what it asked for.

    Read off what the procedure declared rather than off what happened,
    because the next run is composed from the same vocabulary and a
    value this never saw cannot be stepped.
    """
    found: list[tuple[Step, Mapping[str, Any]]] = []
    for step in case.steps:
        asked = step.asked
        if asked.get("kind") != RUN:
            continue
        parameters = asked.get("parameters")
        if isinstance(parameters, dict) and asked.get("operation_id"):
            found.append((step, cast("Mapping[str, Any]", parameters)))
    return found


class Ladder:
    """Climbs one parameter of the last run until a ceiling is reached."""

    def conclude(self, case: Case) -> Conclusion:
        """Say what should happen next, given what happened."""
        broken = [step for step in case.steps if faulted(step)]
        if broken:
            return Refer(
                said=(
                    f"{len(broken)} of {len(case.steps)} steps did not go well: "
                    f"{_listed(broken)}. Climbing further would ask for more of "
                    "something that has not worked once."
                )
            )

        unreached = case.unreached()
        if unreached and case.ended:
            return Refer(
                said=(
                    f"The execution was closed with {len(unreached)} of "
                    f"{len(case.steps)} steps never reached, and nothing here says "
                    "why. Somebody should read the record."
                )
            )
        if unreached:
            return Abstain(
                said=(
                    f"{len(unreached)} of {len(case.steps)} steps have not reported "
                    "and the execution is still open, so there is nothing to climb "
                    "from yet."
                )
            )

        rungs = _rungs(case)
        if not rungs:
            return Abstain(
                said=("Nothing here asked an engine to run, so there is no run to ask for again.")
            )

        step, parameters = rungs[-1]
        if step.became is None or step.became.reported != DONE:
            return Abstain(
                said=(
                    f"The last run {ended_badly(step)} rather than finishing, so "
                    "there is nothing to climb from."
                )
            )

        standing = parameters.get(RUNG)
        if not isinstance(standing, int) or isinstance(standing, bool):
            return Abstain(
                said=(
                    f"The last run did not carry {RUNG} as a whole number, so this "
                    "strategy has no rung to step."
                )
            )

        if standing >= CEILING:
            if case.objective is None:
                return Abstain(
                    said=(
                        f"{RUNG} is at {standing}, which this strategy treats as "
                        "enough. No objective was given, so there is nothing to "
                        "say this met."
                    )
                )
            return Stop(
                said=(
                    f"{RUNG} reached {standing}, which this strategy treats as the "
                    "objective met. A further run would be waste."
                )
            )

        raised = min(standing * 2, CEILING)
        return Propose(
            operation_id=str(step.asked["operation_id"]),
            parameters={**parameters, RUNG: raised},
            said=(
                f"The last run finished cleanly at {RUNG} {standing}. Asking for "
                f"the same run at {raised}, which is the next rung before "
                f"{CEILING}."
            ),
        )


def _listed(steps: list[Step]) -> str:
    """The steps by index and the word each ended on, for a `said`."""
    return ", ".join(f"step {step.index} {ended_badly(step)}" for step in steps)


def inference(looking: Looking) -> Concluding:
    """Hand back the thinking, which is what the profile setting calls.

    The next rung is a function of the parameters the case already
    carries, so `looking` goes unused here. Taken and ignored, which is
    the one shape every profile is built to.

    Annotated with the Protocol rather than with the class, so a type
    checker reads this file as a claim that the class satisfies the seam
    and fails here if it stops doing so.
    """
    return Ladder()
