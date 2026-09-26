"""Answer one question about one execution, and write down what was concluded.

Three moves in a fixed order, once per invocation:

    read      ask the keeper what the execution was asked to do and what
              became of it, and pair the two halves into a case
    conclude  hand the case to whatever does the thinking
    record    write the conclusion down, and the proposal first if the
              conclusion produced one

There is no loop. A conductor has one because work is dispatched to it and
it has to go looking; a thinker is handed one question, answers it, and
exits. What it is handed is now an id either way, and the difference
between a question this thinker opened and one it was given is settled
before this function is called.

## All four conclusions are written now, and one of them twice

`Propose` was once the only one the keeper had a place for, and the other
three were returned to the caller and went no further. This module's own
note on that said the arrangement held only because something was waiting
for the answer, and that it would stop holding the day nobody was. The
keeper has since grown a record for the asking, so the arrangement is
gone: every conclusion lands on the inquiry it answers, and a thinker that
looked and found nothing is no longer indistinguishable from one that
never ran.

`Propose` writes twice, and the order is load bearing. The proposal goes
first and the answer cites it, so a thinker that dies between them leaves
a proposal that reads as any other actor's, which is the harmless
direction. The reverse would leave an inquiry naming a proposal nobody
made, which is a record pointing at nothing.

## What is not caught here

Anything. A keeper that cannot be reached and a provider that raised both
stop this, and neither becomes a conclusion. The alternative would be to
return `Abstain` on a failure, which reads as a thinker that looked and
found nothing, and is a thinker that did not look.

That is the same call `apps/conductor` makes in the other direction and
for the same reason: it refuses to report `Broken` for a step no seam ran,
because unsticking a queue is not worth a false line in a permanent record.

## Why the case comes back

So that whoever invoked this can be shown what was read before being shown
what was concluded. A conclusion is only as good as the case behind it, and
the commonest way for one to be wrong is for the case to be thinner than
the reader assumed: an execution whose record covers two of its six steps
supports very little, and the only way to notice is to see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from thinker.case import assemble
from thinker.conclusions import Propose

if TYPE_CHECKING:
    from thinker.case import Case, Question
    from thinker.conclusions import Conclusion
    from thinker.seams import Inference, Keeper


@dataclass(frozen=True, slots=True)
class Thought:
    """One thinking, from what was read to what was written.

    `inquiry_id` is what the conclusion was written against, and it is
    never None: a thinking that reached no record is not one this function
    can produce.

    `proposal_id` is None for three of the four conclusions, and that is
    not a failure to record them. Those three are on the inquiry like the
    fourth; what they do not have is a run put forward, because they did
    not conclude that one should be.
    """

    case: Case
    conclusion: Conclusion
    proposal_id: str | None
    inquiry_id: str


def think(question: Question, *, keeper: Keeper, inference: Inference) -> Thought:
    """Answer one question, and put a run forward if that is the conclusion.

    The question carries both things this used to take separately: which
    execution to read, and what the thinking is toward. The objective now
    crosses the seam because the record holds one, which is the change
    that makes the case reconstructable by whoever reads the answer later.

    Nothing is written until there is a conclusion, so a thinker that dies
    part way through has advised nothing and answered nothing. The inquiry
    it was working on stays claimed and unanswered, which is a state the
    record can show rather than one it has to guess at.

    The boundary is counted from the case rather than taken from anywhere
    else, so what the record says was seen is what the inference was shown.
    """
    case = assemble(keeper.read(question.execution_id), objective=question.objective)
    conclusion = inference.conclude(case)

    proposal_id = (
        keeper.propose(conclusion.plan_id, conclusion.parameters)
        if isinstance(conclusion, Propose)
        else None
    )
    keeper.answer(question.inquiry_id, conclusion, case.boundary(), proposal_id)

    return Thought(
        case=case,
        conclusion=conclusion,
        proposal_id=proposal_id,
        inquiry_id=question.inquiry_id,
    )


__all__ = ["Thought", "think"]
