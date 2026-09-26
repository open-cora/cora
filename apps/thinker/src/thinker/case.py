"""What a thinker is given to think about: what was asked for, and what came back.

A case is one execution, seen from both sides at once. Every step carries
what the procedure said it should do beside what the record says became of
it, and the pairing is the whole point of the type.

## Why both halves travel, when only one of them is a fact

The record is written by reference to the intent. An execution's step says
how it ended and cites the composed step it was dispatched from; what that
step was asked to do lives in the procedure and nowhere else. The keeper's
own reading route says so, and says not to recover it by taking the step's
description apart.

So a list of outcomes on its own is a list of verdicts with no subjects:
four steps ended, and nothing says what any of them was. Handing an
inference only the record would be handing it that list.

The intent alone is worse in the other direction. A procedure is what
somebody meant to happen, and reading it as an account of what happened is
the failure this package is built to refuse. A chained run has no rollback,
so the only thing that says what a run did is what the run reported.

Pairing them is what makes either legible, and what makes the gap between
them visible at all. A step whose `became` is `None` is one the record does
not cover: neither half says so by itself, because the procedure lists the
step and the record simply has nothing against it.

## The risk of carrying the intent, and where it is answered

Something asked to read a procedure will tend to narrate the procedure as
though it ran. That is the same laundering `apps/conductor` describes at
its acquisition seam, where an engine's own word for how a run ended was
taken for a finding about the run.

The answer is in the shape rather than in a warning. There is no list of
steps and separate list of outcomes to line up wrongly: an outcome sits on
the step it belongs to, `None` is spelled out rather than absent, and
`unreached` exists so that the commonest reading error is a method call
instead of an inference.

## Why the pairing happens here and not in the adapter

An adapter reads two documents and this module joins them. The join is by
id, and a join by position would pass every test there is, because both
lists arrive in the procedure's order today and will keep doing so until
somebody inserts a step. A rule that can be got wrong silently belongs
where every implementation goes through it rather than where each one is
trusted to call it.

`apps/conductor` pairs its own two halves inside its adapter and says why
that is safe there: both are built from one response, in one pass, with no
second writer to drift against. Here they are two responses from two
routes, which is the case that reasoning excludes.

## Why the objective is here and is not read off anything

It is the one thing no record can supply. A record says what happened and
never what it was for, so a thinker asked what should run next without
being told what is being pursued is being asked to guess the question.

It arrives from whoever invoked the thinker. When the keeper grows a record
for the asking, the objective is what that record will carry, and this
field is where it will arrive from instead. `None` is allowed and means the
caller gave none, which is a thinner case rather than a broken one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class MismatchedCaseError(ValueError):
    """An outcome was reported against a step the procedure does not list.

    Raised when the record cites a composed step that is not in the
    procedure it was dispatched from, which can only mean the two halves
    came from different executions or that one of them was misread on the
    way in.

    Steps with no outcome are not this. They are the ordinary shape of a run
    that stopped early, which is most of what a thinker is asked about.
    """


@dataclass(frozen=True, slots=True)
class Reading:
    """The two halves of an execution, as the record hands them over.

    What a `Keeper` returns, and the last shape the keeper's vocabulary
    reaches. `asked` is ordered because a procedure is, and that order is
    what the steps are numbered by. `became` is keyed rather than ordered
    because the record cites the step it reports against, which is the
    thing the two halves are joined on.

    Nothing here has been paired with anything. Pairing is `assemble`'s
    work, and the separation is the point: an adapter that handed over a
    finished `Case` would be an adapter deciding how the halves line up.

    It carries no objective. No record says what an execution was for, so
    there is nothing here to read one out of, and a seam given an argument
    it could only hand straight back would be asking an adapter to carry
    something it has no use for.
    """

    execution_id: str
    procedure: str
    asked: Sequence[tuple[str, Mapping[str, object]]]
    became: Mapping[str, str | None]
    ended: bool


@dataclass(frozen=True, slots=True)
class Step:
    """One step of a procedure, with whatever became of it.

    `asked` is the step as the procedure declares it, passed through rather
    than interpreted. Whether it names a record and a value or a plan and
    its parameters is the keeper's vocabulary, and a thinker that rewrote it
    into one of its own would be deciding what matters before anything has
    read it.

    `became` is the word the record uses for how the step ended, carried
    verbatim for the same reason. `None` means the record says nothing about
    this step, which is what a step the walk never reached looks like.
    """

    index: int
    step_id: str
    asked: Mapping[str, object]
    became: str | None


@dataclass(frozen=True, slots=True)
class Case:
    """One execution, paired with what it was for.

    `ended` is the record's word rather than a count: an execution with an
    outcome for every step has not necessarily been closed, and one that was
    closed early has outcomes for only some. Both are ordinary and they are
    different questions, so both are answerable here.
    """

    execution_id: str
    procedure: str
    steps: Sequence[Step]
    ended: bool
    objective: str | None = None

    def unreached(self) -> Sequence[Step]:
        """The steps the record does not cover.

        Visible only because both halves are here, which is the reason they
        both are. A run that stopped at step two of six leaves four of
        these, and nothing in the record alone counts them.
        """
        return tuple(step for step in self.steps if step.became is None)

    def ran_to_the_end(self) -> bool:
        """Whether every step the procedure lists has an outcome.

        Says nothing about whether any of them succeeded, and nothing about
        whether the execution was closed. A procedure whose every step was
        refused ran to the end by this measure, which is accurate: the walk
        reached the last one.
        """
        return all(step.became is not None for step in self.steps)


def assemble(reading: Reading, *, objective: str | None = None) -> Case:
    """Pair a procedure's steps with the outcomes reported against them.

    By id rather than by position. The keeper's reading route says that a
    composed step's id is what an execution's step cites and what a reader
    comparing the two joins on, so joining any other way would be inventing
    a correspondence beside the one the record already carries.

    Every implementation of the reading seam arrives here, which is the
    reason the seam hands over a `Reading` rather than a finished case. The
    join is the one decision in this package that would look right while
    being wrong, and it is made once.

    `objective` is the caller's and not the record's, so it is added here
    rather than read out of anything.

    A step with no entry in `became` gets `None` and stays in the case. An
    entry in `became` naming no step is refused, because that is not a case
    with an unusual shape, it is two executions.
    """
    listed = {step_id for step_id, _ in reading.asked}
    orphaned = sorted(step_id for step_id in reading.became if step_id not in listed)
    if orphaned:
        raise MismatchedCaseError(
            f"{reading.execution_id}: outcomes reported against {len(orphaned)} step(s) the "
            f"procedure {reading.procedure!r} does not list ({', '.join(orphaned)}), so these "
            "are not both about one execution"
        )

    return Case(
        execution_id=reading.execution_id,
        procedure=reading.procedure,
        steps=tuple(
            Step(index=index, step_id=step_id, asked=detail, became=reading.became.get(step_id))
            for index, (step_id, detail) in enumerate(reading.asked)
        ),
        ended=reading.ended,
        objective=objective,
    )


__all__ = ["Case", "MismatchedCaseError", "Reading", "Step", "assemble"]
