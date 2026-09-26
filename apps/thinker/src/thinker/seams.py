"""The two outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which system of
record a deployment reads and which provider does its thinking are choices
it makes at its entrypoint. That is the arrangement `apps/conductor` uses
for control and acquisition, and the reason is the same one twice over.

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

    from thinker.case import Case, Reading
    from thinker.conclusions import Conclusion


@runtime_checkable
class Keeper(Protocol):
    """Reading what an execution did, and putting a run forward.

    Two verbs, and they are not symmetric. The first reads a record that
    already exists and the second writes one that did not, so an adapter
    that can do the first and not the second is a thinker that can look and
    not advise. That is a supported arrangement rather than a broken one:
    it is what a dry run is.

    Both are translation and neither is judgement. An implementation turns
    whatever it speaks into the two halves of a `Reading`, and turns a
    conclusion into whatever its record takes. What those halves mean, how
    they pair, and which conclusion is worth writing are all decided on the
    near side of this Protocol.
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

    def propose(self, plan_id: str, parameters: Mapping[str, object]) -> str:
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
