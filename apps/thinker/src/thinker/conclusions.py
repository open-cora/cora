"""The four things a thinker may conclude, all four of which are written down.

Distinct classes rather than one record carrying a verdict string, which is
the move `apps/keeper` and `apps/conductor` both make: a field can be set
wrong and a class cannot, and whatever reads a conclusion keys off the class
rather than parsing a word.

## Why there are four when only one puts work forward

A proposal is positive by definition and a start by definition. So a
package whose type had only that arm would have settled the question of
what a thinker may conclude by never providing a way to conclude anything
else, and it would have settled it the same day somebody first needed the
answer to be no.

The other three are not speculative. Each is a different answer to a
different question, and whoever asked gets all four back:

    Propose   run this next
    Stop      the objective is met, and running more would be waste
    Abstain   nothing here warrants a next run that this can see
    Refer     a person should look at this

`Stop` and `Abstain` are the pair most easily collapsed and the pair it
costs most to collapse. `Stop` is a finding about the objective: it is met.
`Abstain` is a finding about the thinker: it sees no next step. One says
the work is over and the other says the thinker is out of ideas, and a
facility told the second when the first was true keeps running, while one
told the first when the second was true stops early.

## Where each of the four goes

Onto the inquiry that asked. All four land there and only `Propose` writes
anywhere else, which is the proposal it puts forward first and then names.

The three that put no work forward are the ones that most needed a record.
A thinker that looked and honestly found nothing is otherwise silence, and
so is one that was never invoked, one that died holding the question, and
one that is not running. `__main__` still prints the word for whoever is
standing there, and something that opens questions without standing over
them has only the record to read.

## What is deliberately not here

**A confidence, a score or a self-evaluation.** A thinker rating its own
conclusion produces exactly the artefact `apps/conductor` refuses at its
engine seam, where the engine's own word for how a run went was taken for
a finding about the run. A number a thinker assigns itself reads as
measurement and is assertion.

**A structured reason.** `said` is free text and is treated as free text.
Parsing it into fields here would turn whatever the inference happened to
phrase into a claim this package makes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Propose:
    """Run this next.

    `operation_id` and `parameters` are what the keeper's proposal takes, in the
    keeper's own terms, because a proposal is refused unless its parameters
    satisfy the schema the operation declares. That check happens at the keeper
    and is worth having there: it is what stops a conclusion phrased
    confidently from becoming a run that could not have worked.

    `said` does not travel with it. The proposal record deliberately carries
    no reason, and a thinker that smuggled one into `parameters` would be
    writing unbounded free text into a table nothing can edit afterwards.
    """

    operation_id: str
    parameters: Mapping[str, object]
    said: str


@dataclass(frozen=True, slots=True)
class Stop:
    """The objective is met and a further run would be waste.

    A claim about the objective rather than about the data, and only as good
    as the objective it was given. A case assembled without one cannot
    honestly produce this, because there is nothing for it to be met.
    """

    said: str


@dataclass(frozen=True, slots=True)
class Abstain:
    """Nothing here warrants a next run that this thinker can see.

    The ordinary answer, and the one a system with no way to record it
    quietly converts into silence. It reaches the inquiry like the other
    three, which is what now separates it from a thinker that was never
    asked and from one that died holding the question: the first leaves the
    inquiry open, the second leaves it claimed, and this leaves it answered.
    """

    said: str


@dataclass(frozen=True, slots=True)
class Refer:
    """A person should look at this.

    Not a failure of the thinker. It is the conclusion for a case whose next
    move is a judgement the thinker is not the right thing to make, which
    includes every case where the record looks wrong rather than
    uninteresting.
    """

    said: str


Conclusion = Propose | Stop | Abstain | Refer


__all__ = ["Abstain", "Conclusion", "Propose", "Refer", "Stop"]
