"""The intent: put several runs forward, in the order they are meant to run."""

from dataclasses import dataclass

from keeper.counsel.aggregates.proposal import ProposedRun


@dataclass(frozen=True)
class ProposePlan:
    """Put forward these runs, in this order, as one piece of advice.

    Propose, not make, and the event this derives is the reason. "Make a
    plan" reads as drawing one up, which is what happened before the call;
    "propose a plan" is the act the call performs, and `PlanProposed` is
    the row a reader of the log can take at its word.

    No aggregate qualifier between the verb and the noun, unlike the
    sub-concept commands beside it. The qualifier is there to say which
    aggregate a flat label acts on, and the verb already says it here:
    proposing is what makes a proposal, so a qualified spelling would name
    the aggregate twice, once as a verb and once as a noun, and read as
    neither.

    **There is no `occurred_at`**, for the reason `MakeProposal` has none:
    proposing is a speech act, and the call is where it was spoken.

    **There is no proposer either.** The handler writes the authenticated
    principal, so a caller cannot advise as somebody else.

    `runs` arrives as the aggregate's own value objects rather than raw
    dictionaries, because both surfaces already parse the caller's JSON
    into something, and a command holding dictionaries would make the
    decider parse them again.
    """

    runs: tuple[ProposedRun, ...]


__all__ = ["ProposePlan"]
