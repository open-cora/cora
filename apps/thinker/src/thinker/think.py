"""Read one execution, conclude something about it, and advise if there is advice.

Three moves in a fixed order, once per invocation:

    read      ask the keeper what the execution was asked to do and what
              became of it, and pair the two halves into a case
    conclude  hand the case to whatever does the thinking
    advise    write the conclusion down, in the one case the record can
              hold it

There is no loop. A conductor has one because work is dispatched to it and
it has to go looking; nothing dispatches to a thinker, and nothing in this
tree reacts to an event by writing another one. So a thinker is invoked,
does this once, and exits. Adding the loop is a smaller change than what
would have to exist for the loop to have anything to ask for.

## Why only one of four conclusions is written

`Propose` is the only one the keeper has a place for. The other three are
returned to the caller and go no further, which is sound precisely because
there is a caller: something invoked this and is waiting for the answer.

The arrangement stops being sound the day a thinker picks its own work.
Then nobody is waiting, an `Abstain` reaches no one, and it becomes
indistinguishable from a thinker that was never asked. That is the change
that earns a record for the asking, and it belongs in the keeper.

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
    from thinker.case import Case
    from thinker.conclusions import Conclusion
    from thinker.seams import Inference, Keeper


@dataclass(frozen=True, slots=True)
class Thought:
    """One thinking, from what was read to what was written.

    `proposal_id` is `None` for three of the four conclusions, and that is
    not a failure to record them. It means the conclusion was not one the
    record has a place for, which is a fact about the keeper rather than
    about the thinking.
    """

    case: Case
    conclusion: Conclusion
    proposal_id: str | None


def think(
    execution_id: str,
    *,
    keeper: Keeper,
    inference: Inference,
    objective: str | None = None,
) -> Thought:
    """Think about one execution, and put a run forward if that is the conclusion.

    `objective` is what the thinking is toward, and it never crosses a
    seam. It is not in the record and the keeper is not asked for it: it
    comes from whoever invoked this thinker and is put on the case here,
    where the case is made.

    The write happens after the conclusion and only for one arm, so a
    thinker that dies partway through has advised nothing. That is the
    right way round: a conclusion nobody heard costs a re-run, and a
    proposal nobody concluded costs a beamline's time.
    """
    case = assemble(keeper.read(execution_id), objective=objective)
    conclusion = inference.conclude(case)

    if isinstance(conclusion, Propose):
        return Thought(
            case=case,
            conclusion=conclusion,
            proposal_id=keeper.propose(conclusion.plan_id, conclusion.parameters),
        )

    return Thought(case=case, conclusion=conclusion, proposal_id=None)


__all__ = ["Thought", "think"]
