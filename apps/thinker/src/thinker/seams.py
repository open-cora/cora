"""The two outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which system of
record a deployment reads and which provider does its thinking are choices
it makes at its entrypoint. That is the arrangement `apps/conductor` uses
for control and run, and the reason is the same one twice over.

Neither Protocol carries a Port suffix. Everything in this module is a seam,
so saying so distinguishes nothing, and `apps/keeper` forbids the suffix for
that reason.

## Two, and why the reading is not a third

An earlier shape had a seam for observing and a separate seam for advising,
on the grounds that reading and writing are different acts. They are, and
they go through one door anyway, because they go to one place: the keeper
holds the executions a thinker reads and the proposals it writes, and
`apps/conductor` already takes one seam holding both the asking and the
reporting for exactly this reason.

A second reading seam earns its place when a thinker observes something the
keeper does not hold. Nothing does yet. There is no stream a thinker can
reach that the keeper is not already the record of, and until there is, a
second Protocol would be one interface with one implementation reading the
same API as the first.

## Every call goes out, and none comes in

A thinker dials the keeper and the keeper never dials back. It is the same
arrangement every other client in this tree has, and it is measured rather
than preferred: nothing in this system can tell a running process anything,
so a thinker is something that is invoked and then asks.

The consequence worth naming is that a thinker cannot steer. A conclusion
reached while an execution is still walking has nowhere to arrive, because
no command in the keeper touches a running execution and the conductor's
verbs are all outbound. Steering is a change to what the keeper and the
conductor are, not a seam that is missing here.

## Why inference is handed a case and not a prompt

The core would otherwise be composing prompts, and how to ask is the thing
that differs most between one provider and the next. Handing over the
domain object leaves the asking entirely inside the adapter, which is where
a change of provider is already going to land.

It comes back as a `Conclusion` for the mirror of that reason. Turning an
answer into one of four classes is provider-specific work, and a seam that
returned text would put unparsed text in the core, where nothing is in a
position to refuse it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from thinker.case import Boundary, Case, Question, Reading
    from thinker.conclusions import Conclusion


@runtime_checkable
class Keeper(Protocol):
    """Reading what an execution did, and writing down what was concluded.

    Five verbs across two records. `read` is the only one about an
    execution; the other four are about an inquiry, which is the record of
    somebody asking and of what came back. `propose` sits between them,
    because a proposal is what one of the four conclusions produces.

    The reading verb and the writing verbs used to be two, and an adapter
    that implemented the first and not the second was described here as a
    dry run. That is no longer what this is. A thinking now ends in a
    record whichever conclusion it reaches, so an implementation that
    cannot write cannot finish, and the honest way to look without
    recording is not to open an inquiry at all.

    Every one of the five is translation and none is judgement. An
    implementation turns whatever it speaks into the halves of a `Reading`
    or the three facts of a `Question`, and turns a conclusion and a
    `Boundary` into whatever its record takes. What those halves mean, how
    they pair, how much of the execution was covered and which conclusion
    is worth which write are all decided on the near side of this Protocol.
    """

    def read(self, execution_id: str) -> Reading:
        """Read one execution, and what the procedure behind it asked for.

        More than one request, because the keeper answers in more than one
        place: an execution's record says how its steps ended, and what
        those steps are is the procedure's to say.

        The halves come back unpaired. Joining them is by id and belongs to
        `assemble`, so that every implementation of this seam joins the
        same way rather than each being trusted to.

        No objective is asked for, because no record holds one. It reaches
        the case from whoever invoked the thinker, on the near side of this
        seam.
        """
        ...

    def ask(self, execution_id: str, objective: str) -> Question:
        """Put a question on the record, and return it with its id.

        The asking is an act the keeper is the authority for, so nothing
        here carries a time: the call is the asking.

        A `Question` comes back rather than a bare id, so that a thinker
        that opened its own question holds exactly what one that was handed
        somebody else's holds. The alternative was for the caller to build
        the second one out of the arguments it just passed, which is a
        second way for the same three facts to come together.

        The objective must be within whatever bound the record declares,
        and an implementation must let a refusal through. A question the
        keeper would not hold is not one to think about and then discover
        has nowhere to land.
        """
        ...

    def question(self, inquiry_id: str) -> Question:
        """Read back a question somebody else put.

        The entry point for a thinker answering an inquiry it did not
        open, which is how a question asked over another surface reaches
        one. What comes back names the execution to read and the objective
        to think toward, so this is the call that replaces both arguments
        the command line used to carry.
        """
        ...

    def claim(self, inquiry_id: str) -> bool:
        """Say this thinker has the question, and report whether it got it.

        False rather than an exception, because being refused is an
        ordinary outcome and not a fault: it means another thinker holds
        the question, or one already answered it. An exception would put
        that beside a keeper that could not be reached, and those want
        opposite handling.

        Nothing here is a lock. The record refuses to say a question was
        taken up twice, which keeps the disagreement in the log, and
        nothing stops a second thinker reading the execution anyway. A
        thinker that respects the False is what makes the claim worth
        having.

        Not called when this thinker opened the question itself. Nobody
        else can hold an id that was minted a moment ago, so the claim
        would record an event that says nothing.
        """
        ...

    def answer(
        self,
        inquiry_id: str,
        conclusion: Conclusion,
        boundary: Boundary,
        proposal_id: str | None,
    ) -> None:
        """Write the conclusion down, whichever of the four it is.

        The verb this seam was missing. Three of the four conclusions
        produce no proposal, and before there was an inquiry to answer they
        reached no record at all, which made a thinker that looked and
        found nothing indistinguishable from one that never ran.

        The boundary travels with the conclusion and is not optional. A
        conclusion drawn from two reported steps of six is a weaker claim
        than the same one drawn from six of six, and once the execution
        moves on nothing can recover which it was.

        `proposal_id` belongs with a `Propose` and with nothing else, and
        it names a proposal `propose` has already written. The record
        refuses the other combinations rather than trusting this.

        Nothing here says who answered. The keeper reads that off the
        authenticated principal, the same way it reads who proposed.
        """
        ...

    def propose(self, operation_id: str, parameters: Mapping[str, object]) -> str:
        """Put a run forward, and return the id of the proposal that records it.

        The proposal is refused unless the parameters satisfy the schema the
        plan declares, and an adapter must let that refusal through rather
        than swallowing it. A conclusion that could not have run is worth
        more as an error than as a row.

        Nothing here says who is proposing. The keeper reads that off the
        authenticated principal, so a thinker is an actor the same way a
        person is, and the credential it holds is what it advises as.
        """
        ...


@runtime_checkable
class Inference(Protocol):
    """Whatever forms a conclusion from a case.

    Deliberately one verb and no configuration. Which model, how it is
    prompted, how many times it is asked and what it costs are all questions
    for the thing behind this, and a Protocol that exposed any of them would
    make the core hold an opinion about a provider it is built not to name.

    An implementation that raises stops the thinking, and nothing above
    catches it. A thinker that could not reach its provider has not
    concluded `Abstain`, and reporting one as the other would put a finding
    into the world that nothing found.
    """

    def conclude(self, case: Case) -> Conclusion:
        """Say what should happen next, given what happened."""
        ...


__all__ = ["Inference", "Keeper"]
