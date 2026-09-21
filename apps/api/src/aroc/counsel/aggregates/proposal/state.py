"""Proposal state and its domain errors.

A Proposal is a run an actor put forward, before anything has run it.

## Who an actor is here

Whoever authenticated. The principal must be an active Actor in Access,
and an actor there is a person, a service account or a background
process, so a scientist putting a run forward and a piece of software
doing it produce the same record. Nothing in this context asks which,
and which of them a deployment permits is Authority's to say rather
than this aggregate's.

That is also why nothing here records the kind. It would be a copy of a
fact Access owns, and Access does not hold one today, so "was this run
human-directed" is a question the record cannot answer. If it needs
answering, a typed marker on the Actor is where it goes.

## What it is not

It cites a plan, it does not contain one, which is the posture the Run
aggregate takes for the same reason: the plan is a record on another
stream, and a copy here would go stale the first time somebody defined a
new one.

That leaves a proposal and a run carrying the same two fields, and the
difference between them is the third. A run carries an external
reference, because a run this system cannot point back at is a claim
that something happened somewhere with no way to check it. A proposal
has nothing to point at. That is not a missing field, it is the whole
distinction: this is the one record in the tree that refers to no act at
all.

## Why this is not a status on a Run

Modelling a proposal as a run that has not started would save a context,
and three things stop it.

A run's genesis requires an external reference, so admitting a pre-start
status means making that field optional and giving up the invariant the
reported shape rests on. It would also break what Running means, which
is that no ending has been reported and no pause stands over it; a
status in front of it would add "and something told us it began", which
is a second claim on one word. And a proposal nothing came of would be a
run that never ran, sitting in every count of how many runs there were.

## Why there is no status field

`run_id is None` is the whole of it. A run derives a five-valued status
in its fold because no single field carries it; here a two-valued enum
beside a nullable field would be the same fact written twice.

An enum arrives at the third state. Withdrawing and superseding are the
two candidates, and the first to land is what stops the answer being
readable off one field.

Open is the honest default and stays honest the way Running does: it
says only that nothing has reported a run against this proposal. A
proposal nobody acted on reads as open forever, and closing that needs
something watching rather than another value.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


class ProposalNotFoundError(Exception):
    """A query named a proposal id with no stream behind it."""

    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Proposal {proposal_id} not found")
        self.proposal_id = proposal_id


class ProposalAlreadyExistsError(Exception):
    """Making one was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because the handler mints a
    fresh id and a fresh id has no history. It exists so the decider
    states the precondition it relies on rather than assuming it.
    """

    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Proposal {proposal_id} already exists")
        self.proposal_id = proposal_id


class InvalidProposalParametersError(ValueError):
    """The proposed values do not satisfy the plan's declared schema.

    A proposal that could not be run is not a proposal, so the values
    are checked against the same schema, by the same shared validator,
    that checks a run's. Its own class rather than Execution's, because
    the two are refused on different surfaces and a caller reading
    `InvalidRunParametersError` from a proposal endpoint would go
    looking for a run.
    """


class ProposalCannotBeTakenError(Exception):
    """A run cannot be recorded against this proposal.

    Two causes, one class, which is the shape `RunCannotBePausedError`
    already uses: one verb, more than one way to be refused, and the
    discriminating state carried on the error rather than split across
    class names. R6 is about not collapsing several VERBS into one
    class, and there is one verb here.

    The causes are told apart by `taken_by`. Set, the proposal already
    has a run against it. Unset, the cited run names a different plan
    from the one proposed, and the two plan ids say which.

    Both are 409 because the caller's next move is the same in kind:
    stop, and work out which run it meant.
    """

    def __init__(
        self,
        proposal_id: UUID,
        detail: str,
        *,
        taken_by: UUID | None = None,
        proposed_plan_id: UUID | None = None,
        run_plan_id: UUID | None = None,
    ) -> None:
        super().__init__(f"Proposal {proposal_id} cannot be taken: {detail}")
        self.proposal_id = proposal_id
        self.taken_by = taken_by
        self.proposed_plan_id = proposed_plan_id
        self.run_plan_id = run_plan_id

    @classmethod
    def already_taken(cls, proposal_id: UUID, taken_by: UUID) -> "ProposalCannotBeTakenError":
        """A run is already recorded against it."""
        return cls(
            proposal_id,
            f"run {taken_by} already took it",
            taken_by=taken_by,
        )

    @classmethod
    def plan_mismatch(
        cls, proposal_id: UUID, *, proposed_plan_id: UUID, run_plan_id: UUID
    ) -> "ProposalCannotBeTakenError":
        """The cited run ran a different plan from the one proposed."""
        return cls(
            proposal_id,
            f"it proposes plan {proposed_plan_id} and run ran plan {run_plan_id}",
            proposed_plan_id=proposed_plan_id,
            run_plan_id=run_plan_id,
        )


@dataclass(frozen=True)
class Proposal:
    """A run an actor put forward, as the fold leaves it.

    `actor_id` is whoever proposed, written by the handler from the
    authenticated principal rather than supplied by the caller. It
    duplicates the envelope's `principal_id` on purpose: the envelope is
    infrastructure and the fold never sees it, and who advised is a
    domain question that should be answerable from the domain record.

    Named for the aggregate it points at, the way `run_id` and `plan_id`
    are. The role it plays is carried by the record it sits on rather
    than by a second word in the field name.

    `run_id` is None until a run is recorded against it, and is what
    says whether this proposal is still open.
    """

    id: UUID
    actor_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    run_id: UUID | None = None

    @property
    def is_taken(self) -> bool:
        """Whether a run has been recorded against this proposal.

        A property rather than a stored flag, for the reason a run's
        status is derived: a field a writer can set is a field a writer
        can set wrong, and this one cannot disagree with the join it
        reads.
        """
        return self.run_id is not None


__all__ = [
    "InvalidProposalParametersError",
    "Proposal",
    "ProposalAlreadyExistsError",
    "ProposalCannotBeTakenError",
    "ProposalNotFoundError",
]
