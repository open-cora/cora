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

## Why an outcome is three facts and not one word

The keeper holds two claims about how a step ended and refuses to collapse
them, so this does not collapse them either. One is the driver's: the call
returned, raised, or was stopped by a claim conflict before it touched
anything. The other is the engine's own account of the run the step opened,
relayed by whatever watches that engine.

They can disagree, and that disagreement is the case worth carrying both
for. A run step whose seam returned cleanly and whose engine then failed is
reported `Done` with an engine state of `Failed`, so a thinker shown only
the first word reads a run that broke as a run that worked, and reads it
with no sign that a second word existed. Choosing between them here would
also be this package settling a disagreement between two observers it
cannot check, which is the keeper's own reason for holding them apart.

The third fact is the cause, an exception's class name and never its
message, because a class name is all the record will hold: free failure
text is refused over there on purpose. So a case says what kind of thing
went wrong and never why, and anything needing the why needs a seam onto
something other than the record.

## The risk of carrying the intent, and where it is answered

Something asked to read a procedure will tend to narrate the procedure as
though it ran. That is the same laundering `apps/conductor` describes at
its engine seam, where the engine's own word for how a run ended was taken
for a finding about the run.

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

## Why the objective is here and is not read off the execution

No execution record supplies it. A record says what happened and never what
it was for, so a thinker asked what should run next without being told what
is being pursued is being asked to guess the question.

It arrives on a `Question`, which is the inquiry's account of the asking
and carries the objective that inquiry was opened with. `None` is still
allowed here, where it is not on a `Question`, because a case can be
assembled without an inquiry at all. On the path this package runs there
is always one.
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
class Question:
    """What was asked, as the record holds it.

    The other thing a keeper hands over, and the half `Reading` cannot
    supply. A reading says what an execution did; this says what somebody
    wanted to know about it, which no execution record contains.

    It comes back from reading an inquiry the record already holds, and it
    comes back from opening one, because both end with the same three
    facts in hand and a caller that had to assemble the second case itself
    would be assembling it differently from the first.

    `objective` is not optional here, where it is on a `Case`. An inquiry
    with no question is a record whose answer cannot be read, so the
    keeper refuses one, and by the time a question exists it has one.
    """

    inquiry_id: str
    execution_id: str
    objective: str


@dataclass(frozen=True, slots=True)
class Boundary:
    """How much of the execution the thinker had in front of it.

    Two facts rather than one, because they answer two questions. An
    execution can be closed with steps nobody reported on, and one with an
    outcome against every step has not necessarily been closed.

    It says how much was visible and never whether the conclusion drawn
    from it was good. That distinction is the whole reason this is a pair
    of plain counts and not a score: a number a thinker assigns its own
    answer reads as measurement and is assertion.

    Derived from a case rather than reported by whatever read it, so the
    two cannot disagree: what goes on the record is counted from the same
    steps the inference was shown.
    """

    observed_step_count: int
    execution_ended: bool


@dataclass(frozen=True, slots=True)
class Outcome:
    """How one step ended, in the words of everything that reported on it.

    Three fields because the record holds three facts about an ended step,
    and each is the keeper's own word passed through rather than rewritten.
    A step that set a record opened no run and so has no engine to hear
    from, which is what `engine_state` being `None` means; a step that
    ended any way but breaking carries no `cause`.

    Nothing here says whether the step went well. A method that did would
    have to know which of the keeper's words mean well, and choosing that
    is the same interpretation `Step` declines to perform on the intent it
    carries. Whatever reads a case is shown the words and decides.
    """

    reported: str
    engine_state: str | None
    cause: str | None


@dataclass(frozen=True, slots=True)
class Reading:
    """The two halves of an execution, as the record hands them over.

    What `Observing` returns, and the last shape the keeper's vocabulary
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
    became: Mapping[str, Outcome | None]
    ended: bool


@dataclass(frozen=True, slots=True)
class Step:
    """One step of a procedure, with whatever became of it.

    `asked` is the step as the procedure declares it, passed through rather
    than interpreted. Whether it names a record and a value or an operation and
    its parameters is the keeper's vocabulary, and a thinker that rewrote it
    into one of its own would be deciding what matters before anything has
    read it.

    `became` is what the record says became of it, carried verbatim for the
    same reason and in every word the record uses rather than only the
    first. `None` means the record says nothing about this step, which is
    what a step the walk never reached looks like, and it stays the one
    structural fact here: every count a case offers tests for it, and none
    of them reads a word.
    """

    index: int
    step_id: str
    asked: Mapping[str, object]
    became: Outcome | None


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

    def boundary(self) -> Boundary:
        """What the record covered, in the shape the keeper writes down.

        Counted here rather than reported by the caller, for the reason the
        join is made here: it is the one place that has both the steps the
        inference saw and the record's own word for whether the execution
        was closed, so a boundary built anywhere else could describe a
        different reading than the one that produced the conclusion.

        A step with no outcome does not count as observed. That is the same
        rule `unreached` states, and the two are deliberately the same
        arithmetic read from opposite ends.
        """
        return Boundary(
            observed_step_count=sum(1 for step in self.steps if step.became is not None),
            execution_ended=self.ended,
        )

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


__all__ = [
    "Boundary",
    "Case",
    "MismatchedCaseError",
    "Outcome",
    "Question",
    "Reading",
    "Step",
    "assemble",
]
