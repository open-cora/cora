"""A thinking that reads the record and never asks for anything to run.

The reference profile. `inference.profile` names something importable that
hands back whatever does the thinking, and until this existed there was
nothing in this repository to name, so a thinker could not start anywhere.

## What it will and will not conclude

Three of the four conclusions. It reaches `Stop`, `Abstain` and `Refer`,
and never `Propose`, so nothing it decides can become work at a beamline.
That is a property of this profile rather than a limit of the seam: a
profile that proposes is a different file behind the same dotted path.

```
    any step Broken, or an engine that Aborted or Failed  ->  Refer
    the execution ended with steps it never reached       ->  Refer
    steps not reached and the execution still open        ->  Abstain
    every step Done, engines clean, an objective given    ->  Stop
    anything else                                         ->  Abstain
```

## Why it reads two words per step and not one

A run whose seam returned cleanly and whose engine then failed is reported
`Done` with an engine state of `Failed`. `thinker.case` says so where it
explains why an outcome is three facts, and the disagreement is the reason
the record keeps both. A table reading only the first word calls that run
clean and concludes the objective was met, which is the laundering the
same page warns about, so an engine fault is checked beside the driver's
word everywhere it matters.

## Why a case with no objective never stops

`Stop` is a claim that the objective is met, and `thinker.conclusions`
states that a case assembled without one cannot honestly produce it. Those
cases abstain instead, which is accurate: a clean run with nothing asked of
it is a clean run nobody can say is enough.

## Why the keeper's words are spelled here

They arrive as the record's own strings, carried through without being
interpreted, and this is the first thing on this side that interprets them.
Nothing in `thinker` holds a list of them to import, and importing the
keeper is not available to a client that ships as its own repository. So
they are literals, and they are compared against the keeper's own
enumerations by a check in the development tree that holds both
repositories, because a word nothing compares is a rename away from a
table that quietly stops matching and abstains on everything.

That check cannot live here. This repository ships without the keeper
beside it, so the comparison is only possible where both are, which is
the same reason the words are literals in the first place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from thinker.conclusions import Abstain, Refer, Stop

if TYPE_CHECKING:
    from thinker.case import Case, Step
    from thinker.conclusions import Conclusion
    from thinker.seams import Concluding

DONE: Final = "Done"
"""The keeper's word for a step whose driver returned."""

BROKEN: Final = "Broken"
"""The keeper's word for a step whose driver raised."""

ABORTED: Final = "Aborted"
FAILED: Final = "Failed"

ENGINE_FAULTS: Final[frozenset[str]] = frozenset({ABORTED, FAILED})
"""The engine's own terminal words for a run that did not finish well.

The engine's third terminal word, for a run that finished, is absent on
purpose. So is the empty state a step that opened no run carries, and
reading that as a fault would refer every procedure that only sets
records.
"""


def _faulted(step: Step) -> bool:
    """Whether either observer said this step went wrong.

    Either, not both. The two can disagree and neither is checkable from
    here, so a fault reported by one is a fault.
    """
    became = step.became
    if became is None:
        return False
    return became.reported == BROKEN or became.engine_state in ENGINE_FAULTS


class Advisory:
    """Reads a case against a small table and says what it sees.

    Holds nothing and reaches nothing, so one instance serves every
    thinking and there is no state to carry between them.
    """

    def conclude(self, case: Case) -> Conclusion:
        """Say what should happen next, given what happened."""
        faulted = [step for step in case.steps if _faulted(step)]
        if faulted:
            return Refer(
                said=(
                    f"{len(faulted)} of {len(case.steps)} steps did not go well: "
                    f"{_listed(faulted)}. Somebody should read the record before "
                    "anything else is run."
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
                    "and the execution is still open, so there is nothing to "
                    "conclude yet."
                )
            )

        if not case.steps:
            return Abstain(said="The procedure has no steps, so there is nothing to read.")

        undone = [
            step for step in case.steps if step.became is not None and step.became.reported != DONE
        ]
        if undone:
            return Abstain(
                said=(
                    f"Every step reported and {len(undone)} of {len(case.steps)} did "
                    f"not run: {_listed(undone)}. Nothing broke, and nothing here "
                    "says whether that was intended."
                )
            )

        if case.objective is None:
            return Abstain(
                said=(
                    f"All {len(case.steps)} steps are done and nothing faulted. No "
                    "objective was given, so there is nothing to say this met."
                )
            )

        return Stop(
            said=(
                f"All {len(case.steps)} steps are done, the driver and the engine "
                "agree, and the objective is met. A further run would be waste."
            )
        )


def _listed(steps: list[Step]) -> str:
    """The steps by index and the word each ended on, for a `said`.

    Indexes rather than ids, because a `said` is read by a person next to
    the procedure and an id is the long way to find the same row.
    """
    return ", ".join(f"step {step.index} {_word(step)}" for step in steps)


def _word(step: Step) -> str:
    """How one step ended, in whichever words the record used.

    Both when they disagree, because that disagreement is the reason a
    reader is being sent to the record.
    """
    became = step.became
    if became is None:
        return "never reported"
    if became.engine_state is None:
        return became.reported
    return f"{became.reported} with an engine that {became.engine_state}"


def inference() -> Concluding:
    """Hand back the thinking, which is what `inference.profile` calls.

    A function rather than the instance, because the entrypoint calls what
    the profile names and a deployment building a client with credentials
    needs somewhere to build it.

    Annotated with the Protocol rather than with `Advisory`, so a type
    checker reads this file as a claim that the class satisfies the seam
    and fails here if it stops doing so. The entrypoint casts rather than
    checks, and says why, which leaves this the only place the structural
    check can happen before a deployment finds out.
    """
    return Advisory()
