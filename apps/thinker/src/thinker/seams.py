"""The six outward seams, named for what a thinker does through them.

A seam is a Protocol here and an adapter under `thinker.adapters`, so
which system of record a deployment reads and which provider does its
thinking are choices it makes at its entrypoint. That is the arrangement
`apps/conductor` uses, and the reason is the same one twice over.

None of the Protocols carries a Port suffix. Everything in this module is
a seam, so saying so distinguishes nothing, and `apps/keeper` forbids the
suffix for that reason.

## Five doors to the keeper, where one would have been the same place

`Seeking`, `Claiming`, `Observing`, `Questioning` and `Advising` all reach
the keeper today, and one adapter implements all five. They are five
Protocols anyway, because they are five things a thinker does: go looking
for a question, take one up, read what an execution did, keep a record of
somebody asking, and put a conclusion and a run forward.

Three of them were once one Protocol with six verbs, on the argument
that reading and writing go through one door because they go to one
place. One place is a fact about the adapter. Nothing above needs to
know it, one class can satisfy all of them, and the entrypoint passes
the same object as many times as it takes, so the argument was buying
nothing and costing the thing below.

What it costs is that no caller uses the whole port. `think` reads,
proposes and answers; the loop takes and claims. Neither ever wanted the
other's verbs, and a fat port would hand each of them verbs it must
never call. `think` is handed exactly what it uses and cannot take a
question or claim one, which is not a rule anybody has to follow.

`Seeking` is separate from `Questioning` by that same rule. Finding work
and keeping the record of it are two subjects, and only the loop wants
the first.

`Claiming` is separate for the same reason, and for a while was not,
which made this the one place the rule above was stated and then broken.
`claim` sat on `Questioning` because taking a question up is a fact
about that question's record, which it is. It is also the only verb here
that two callers want: the loop claims what it just found, and a thinker
handed an inquiry id on a command line claims that. So wherever it sits
beside something, the other caller is given a verb it must never call,
and the loop was the caller that got them. Its own Protocol is what
costs neither of them anything.

## Every call goes out, and none comes in

A thinker dials the keeper and the keeper never dials back. It is the
same arrangement every other client in this tree has, and it is measured
rather than preferred: a survey of the beamlines this is pointed at found
each one reaching a central host and not the reverse.

A waiting thinker does not change that, which is the whole reason the
waiting is shaped the way it is. `take` holds a request this side opened,
so being told that a question exists arrives as the answer to an outbound
call. Nothing here listens, and a thinker needs no inbound port and no
second credential at the host it runs on.

The consequence worth naming is that a thinker cannot steer. A conclusion
reached while an execution is still walking has nowhere to arrive,
because no command in the keeper touches a running execution and the
conductor's verbs are all outbound. Steering is a change to what the
keeper and the conductor are, not a seam that is missing here.

## Another reading seam earns its place when a thinker observes something else

`Observing` reads the keeper because the keeper is the record of
everything a thinker can currently see. There is no stream it can reach
that the keeper is not already the record of, and until there is, a
second reading Protocol would be one interface with one implementation
reading the same API as the first.

`Seeking` is not that one. It reads the same record through the same
adapter, and it is here because what it does with what it reads is
different in kind: it finds the work rather than describing it.

## Why inference is handed a case and not a prompt

The core would otherwise be composing prompts, and how to ask is the
thing that differs most between one provider and the next. Handing over
the domain object leaves the asking entirely inside the adapter, which
is where a change of provider is already going to land.

It comes back as a `Conclusion` for the mirror of that reason. Turning an
answer into one of four classes is provider-specific work, and a seam
that returned text would put unparsed text in the core, where nothing is
in a position to refuse it.

## Why `answer` takes a proposal id that is usually nothing

Three of the four conclusions produce no proposal, so three of four
callers pass `None`, and a seam that makes an invalid combination
representable is usually worth reshaping. This one is not.

The pairing is a rule about the record rather than about this call: a
proposal id belongs with `Propose` and with nothing else, and the keeper
refuses every other combination rather than trusting a caller. Moving
the id onto the conclusion would mean rebuilding a conclusion after
proposing, and folding the two verbs into one would hide that a proposal
is written before an answer is, which is the order a failure between
them is read by.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from thinker.case import Boundary, Case, Question, Reading
    from thinker.conclusions import Conclusion


@runtime_checkable
class Observing(Protocol):
    """Reading what an execution was asked to do, and what became of it."""

    def read(self, execution_id: str) -> Reading:
        """Read one execution, and what the procedure behind it asked for.

        More than one request behind this, because the record answers in
        more than one place: an execution says how its steps ended, and
        what those steps are is the procedure's to say.

        The halves come back unpaired. Joining them is by id and belongs
        to `assemble`, so that every implementation of this seam joins
        the same way rather than each being trusted to.

        No objective is asked for, because no execution record holds
        one. It arrives with the question, whether that was taken off
        the record or named on a command line, and reaches the case on
        the near side of this seam.
        """
        ...


@runtime_checkable
class Seeking(Protocol):
    """Going looking for a question nobody has taken up."""

    def take(self, wait: float) -> Question | None:
        """Ask for one question to answer, and hold the ask open for a while.

        None when the wait ran out with nothing there, which is most of
        what a quiet facility returns and is not a failure.

        `wait` asks the record to hold the request rather than answer an
        empty page, so a thinker sits on one open connection instead of
        asking every few seconds. It is a bound on the socket and not on
        anybody's patience: nothing is lost when it runs out, because a
        question sits there until something takes it, and the next ask
        returns it.

        A whole `Question` rather than an id, because the record's
        listing already carries all three facts one holds. Handing back
        an id would mean reading the same row again through another verb
        to recover what this one had.

        Nothing narrows the ask. A conductor asks for its own beamline
        because work is dispatched to one, and an inquiry has no
        beamline: it names an execution, and where that ran is a fact
        about the execution. So a thinker takes whatever is open, and two
        thinkers reaching for one question is settled by the claim rather
        than by dividing the work up beforehand.
        """
        ...


@runtime_checkable
class Questioning(Protocol):
    """Keeping the record of somebody asking."""

    def ask(self, execution_id: str, objective: str) -> Question:
        """Put a question on the record, and return it with its id.

        The asking is an act the record is the authority for, so nothing
        here carries a time: the call is the asking.

        A `Question` comes back rather than a bare id, so that a thinker
        that opened its own question holds exactly what one handed
        somebody else's holds. The alternative was for the caller to
        build the second one out of the arguments it just passed, which
        is a second way for the same three facts to come together.

        The objective must be within whatever bound the record declares,
        and an implementation must let a refusal through. A question the
        record would not hold is not one to think about and then
        discover has nowhere to land.
        """
        ...

    def read_back(self, inquiry_id: str) -> Question:
        """Read back a question somebody else put.

        The entry point for a thinker answering an inquiry it did not
        open, which is how a question asked over another surface reaches
        one. What comes back names the execution to read and the
        objective to think toward, so this is the call that replaces
        both arguments the command line used to carry.

        Two words because the one word is taken, and the two-word
        version is what the line above already called it. `Observing`
        spells its own fetch `read` and one adapter satisfies both
        seams, so a second `read` with a different signature would mean
        splitting that adapter in order to rename a method.

        What this replaced was the one-word spelling, which parsed and
        did not read aloud: a `Questioning` returning a `Question` from
        a call named for the same word is that word doing three jobs,
        and it was the only verb across the seams of this tree that was
        a noun. Being two words also brings it inside the citation
        check, which skips a bare lowercase token because prose cannot
        be told from code at that shape.
        """
        ...


@runtime_checkable
class Claiming(Protocol):
    """Taking a question up, so a second thinker does not spend on it too."""

    def claim(self, inquiry_id: str) -> bool:
        """Say this thinker has the question, and report whether it got it.

        False rather than an exception, because being refused is an
        ordinary outcome and not a fault: it means another thinker holds
        the question, or one already answered it. An exception would put
        that beside a record that could not be reached, and those want
        opposite handling.

        A bool rather than the means of answering, which is the shape
        `apps/conductor` gives its claim. The two look alike and are
        not. A conductor's claim is the only thing standing between two
        drivers and one piece of hardware, so binding the reporting to
        it is worth the asymmetry. Nothing is locked here: the record
        refuses to say a question was taken up twice, which keeps the
        disagreement in the log, and nothing stops a second thinker
        reading the execution anyway. A thinker that respects the False
        is what makes the claim worth having.

        It is also a Protocol of its own here and a second verb on that
        conductor's taking, and what differs is how many callers want
        it. A conductor claims in one place, the loop that took the
        work. A thinker claims in two, and a verb wanted by two callers
        with different companions belongs beside neither of them.

        Never asked for a question this thinker opened itself, which is
        a precondition the caller carries and not something to check
        for here: nobody else can hold an id minted a moment ago, so
        the claim would record an event that says nothing. Which of the
        two ways in is which is settled where the command line is read.
        """
        ...


@runtime_checkable
class Advising(Protocol):
    """Putting a run forward, and writing down what was concluded."""

    def propose(self, operation_id: str, parameters: Mapping[str, object]) -> str:
        """Put a run forward, and return the id of the proposal recording it.

        The proposal is refused unless the parameters satisfy the schema
        the operation declares, and an adapter must let that refusal
        through rather than swallowing it. A conclusion that could not
        have run is worth more as an error than as a row.

        Nothing here says who is proposing. The record reads that off
        the authenticated principal, so a thinker is an actor the same
        way a person is, and the credential it holds is what it advises
        as.
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

        Three of the four produce no proposal, and before there was an
        inquiry to answer they reached no record at all, which made a
        thinker that looked and found nothing indistinguishable from one
        that never ran.

        The boundary travels with the conclusion and is not optional. A
        conclusion drawn from two reported steps of six is a weaker
        claim than the same one drawn from six of six, and once the
        execution moves on nothing can recover which it was.

        `proposal_id` names a proposal `propose` has already written.
        See the module docstring for why it is a nullable argument
        rather than a shape that could not be got wrong.

        Nothing here says who answered. The record reads that off the
        authenticated principal, the same way it reads who proposed.
        """
        ...


@runtime_checkable
class Concluding(Protocol):
    """Whatever forms a conclusion from a case.

    Deliberately one verb and no configuration. Which model, how it is
    prompted, how many times it is asked and what it costs are all
    questions for the thing behind this, and a Protocol that exposed any
    of them would make the core hold an opinion about a provider it is
    built not to name.

    Named for what the core needs rather than for how it is done. An
    inference is one way to reach a conclusion and a table of rules is
    another, and a deployment running the second should not implement
    something whose name says it is doing the first.

    An implementation that raises stops the thinking, and nothing above
    catches it. A thinker that could not reach its provider has not
    concluded `Abstain`, and reporting one as the other would put a
    finding into the world that nothing found.
    """

    def conclude(self, case: Case) -> Conclusion:
        """Say what should happen next, given what happened."""
        ...


__all__ = ["Advising", "Claiming", "Concluding", "Observing", "Questioning", "Seeking"]
