"""Proposal state and its domain errors.

A Proposal is a run an actor put forward, or several in order, before
anything has run them.

## One run or several, and why both are one aggregate

A proposal made with `make_proposal` puts forward one run. A plan, made
with `propose_plan`, puts forward up to `PROPOSAL_MAX_RUNS` of them in the
order they are meant to run: a collection, the transfer of its data, the
reconstruction of it somewhere else, and the transfer of the result back.
Both are advice, both are adopted, cited by an answer and read back the
same way, so a plan is a proposal rather than a sibling of one, and the
state holds a sequence of runs either way. A proposal of one run is read
as a plan of one, which is what lets every proposal already on the
record keep folding exactly as it did.

The runs are one piece of advice rather than several. They are adopted
together, into one procedure and one execution, and refused together: one
run that cannot be proposed or composed refuses the whole plan, because
running the first half of a collection and its transfer is not something
anybody advised.

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

It cites an operation, it does not contain one, which is the posture every
record in this tree that names an operation takes for the same reason: the
operation is a record on another stream, and a copy here would go stale the
first time somebody defined a new one.

That leaves each proposed run carrying what a run step carries, and
the difference between them is that one happened. A run is a
step of a procedure this system composed and dispatched, so something
drove it. A proposal points at nothing at all. That is not a missing
field, it is the whole distinction: this is the one record in the tree
that refers to no act.

## Why this is not a status on an Execution

Modelling a proposal as a step nothing has driven yet would save a
context, and two things stop it.

A step does not exist on its own. It is an entity inside an execution,
which exists because a procedure was dispatched, so a proposal modelled
as a step would need a procedure composed and handed out before anybody
had agreed the work should happen. That is the wrong order: proposing is
what comes before composing.

And a proposal nothing came of would be a step nobody drove, sitting in
every count of how far its execution got.

## Why there is a status field now, when there was not

`execution_id is None` used to be the whole of it, and this page said an
enum would arrive at the third state. Adoption is that third state.

Two ways a proposal can stop being open, and the null test cannot tell
them apart: this system chose it and committed work, or something
outside ran what it proposed and said so afterwards. Both set the same
two fields. The status is what carries the difference, and it is derived
in the fold from which event landed rather than stored, because a status
written onto a payload could contradict the event it rode in on.

Withdrawing and superseding are still the two foreseeable members after
these three.

Open is the honest default and stays honest the way Dispatched does: it
says only that nothing has been recorded against this proposal. A
proposal nobody acted on reads as open forever, and closing that needs
something watching rather than another value.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

PROPOSAL_MAX_RUNS = 16
"""How many runs one proposal may put forward.

The plan this was built for runs four: a collection, the transfer of its
data, a reconstruction somewhere else and the transfer of the result back.
Sixteen leaves room for one that collects at several positions and moves
each result, and stays small beside a procedure's thousand steps on
purpose: a proposal is advice a person may read before adopting it.
"""


class ProposalStatus(StrEnum):
    """What became of the advice, as one word.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is `ExecutionStatus`'s choice and
    `InquiryStatus`'s beside it.

    Derived in the fold from which event landed, never stored.

    Two of the three close the proposal and they are not the same fact.
    `ADOPTED` says this system chose the proposal, chose a beamline and a
    bound for it, and committed the facility: a decision made here, at
    the moment it is written. `TAKEN` says nobody here decided, and a
    step exists somewhere that ran what was proposed.

    There is no terminal property. Unlike an execution or an inquiry,
    nothing further is expected on this stream after either of the two,
    so a reader asking whether more can land is asking a question with
    one answer.
    """

    OPEN = "Open"
    ADOPTED = "Adopted"
    TAKEN = "Taken"


class ProposalCannotBeAdoptedError(Exception):
    """Adoption was attempted on a proposal that was not open.

    Per verb rather than collapsed onto a shared transition error, which
    is R6 in docs/reference/naming.md, and the status is on it because
    the two refusals mean different things. Already adopted is the
    facility committed twice to one piece of advice; already taken is
    advice something else acted on, where composing more work would run
    it a second time.
    """

    def __init__(self, proposal_id: UUID, status: "ProposalStatus") -> None:
        super().__init__(f"Proposal {proposal_id} cannot be adopted while {status}")
        self.proposal_id = proposal_id
        self.status = status


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
    """The proposed values do not satisfy the operation's declared schema.

    A proposal that could not be run is not a proposal, so the values
    are checked against the same schema, by the same shared validator,
    that checks a run's. Its own class rather than Execution's,
    because the two are refused on different surfaces and a caller
    reading `InvalidProcedureParametersError` from a proposal endpoint
    would go looking for a procedure.

    A plan's message names the run, by its place in the plan counted from
    zero, because a plan may run one operation more than once and a
    caller told only that some run is wrong has to check each.
    """


class InvalidProposalRunsError(ValueError):
    """A plan put forward no runs, or more than one proposal may hold.

    A `ValueError`, because it says the input was never well-formed. The
    HTTP surface refuses both shapes before a command is built; this is
    what holds for the MCP surface and for any caller that reaches the
    decider another way.
    """


class ProposalCannotBeTakenError(Exception):
    """A run cannot be recorded against this proposal.

    Four causes, one class, which is the shape
    `ExecutionCannotBeClaimedError` also takes: one verb, more than one
    way to be refused, and the discriminating state carried on the error
    rather than split across class names. R6 is about not collapsing
    several VERBS into one class, and there is one verb here.

    The causes are told apart by which attribute is set. `taken_by` set
    means the proposal already has a step against it. `run_count` set
    means the proposal is a plan of that many runs, which one step cannot
    have taken. `step_operation_id` set means the cited step ran a
    different operation from the one proposed, and the two operation ids
    say which. None set means the cited step runs no operation at all,
    which is a set.

    The fourth cause arrived with the step reference and is genuinely
    distinct rather than a mismatch against nothing. A mismatch tells a
    caller it resolved the wrong run; this tells it that what it
    resolved is not a run, so the fix is not to go looking for
    a closer match.

    All four are 409 because the caller's next move is the same in
    kind: stop, and work out which step it meant, or that no one step is
    what it means.
    """

    def __init__(
        self,
        proposal_id: UUID,
        detail: str,
        *,
        taken_by: UUID | None = None,
        run_count: int | None = None,
        proposed_operation_id: UUID | None = None,
        step_operation_id: UUID | None = None,
    ) -> None:
        super().__init__(f"Proposal {proposal_id} cannot be taken: {detail}")
        self.proposal_id = proposal_id
        self.taken_by = taken_by
        self.run_count = run_count
        self.proposed_operation_id = proposed_operation_id
        self.step_operation_id = step_operation_id

    @classmethod
    def already_taken(cls, proposal_id: UUID, taken_by: UUID) -> "ProposalCannotBeTakenError":
        """A step is already recorded against it.

        `taken_by` is the step, not the execution around it. The step is
        what took the proposal, and an execution long enough to hold a
        thousand of them says almost nothing about which.
        """
        return cls(
            proposal_id,
            f"step {taken_by} already took it",
            taken_by=taken_by,
        )

    @classmethod
    def a_plan_of_several(cls, proposal_id: UUID, run_count: int) -> "ProposalCannotBeTakenError":
        """The proposal puts forward several runs, and a take names one step.

        A take is a report that a step somewhere ran what was proposed. A
        plan proposed several runs in an order, and one step running one of
        them is not the plan being taken; recording it as though it were
        would close advice nobody followed. A plan is closed by adopting
        it, which composes every run together.
        """
        return cls(
            proposal_id,
            f"it is a plan of {run_count} runs, and a take names one step; "
            "a plan is closed by adopting it",
            run_count=run_count,
        )

    @classmethod
    def operation_mismatch(
        cls, proposal_id: UUID, *, proposed_operation_id: UUID, step_operation_id: UUID
    ) -> "ProposalCannotBeTakenError":
        """The cited run ran a different operation from the one proposed."""
        return cls(
            proposal_id,
            f"it proposes operation {proposed_operation_id} "
            f"and the step ran operation {step_operation_id}",
            proposed_operation_id=proposed_operation_id,
            step_operation_id=step_operation_id,
        )

    @classmethod
    def not_an_acquisition(cls, proposal_id: UUID, step_id: UUID) -> "ProposalCannotBeTakenError":
        """The cited step runs no operation, so it cannot have run this one.

        A set, today. What makes this refusable rather than merely
        false is that a proposal proposes running an operation, and a step
        that hands nothing to an engine has not run one whatever else it
        did.
        """
        return cls(
            proposal_id,
            f"step {step_id} runs no operation, and a proposal proposes running one",
        )


@dataclass(frozen=True)
class ProposedRun:
    """One run a proposal puts forward: which operation, with what values.

    It cites an operation and does not contain one, for the reason the
    module docstring gives. The values are what the proposer sent, checked
    against that operation's schema when the proposal was made and stored
    as they arrived rather than normalised.

    No devices and no beamline. Those are decided where the proposal is
    adopted, because nothing about advice can derive them.
    """

    operation_id: UUID
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Proposal:
    """One run or several an actor put forward, as the fold leaves it.

    `actor_id` is whoever proposed, written by the handler from the
    authenticated principal rather than supplied by the caller. It
    duplicates the envelope's `principal_id` on purpose: the envelope is
    infrastructure and the fold never sees it, and who advised is a
    domain question that should be answerable from the domain record.

    Named for the aggregate it points at, the way an `operation_id` is. The
    role it plays is carried by the record it sits on rather than by a
    second word in the field name.

    `runs` holds what was put forward, in order, one or more. A proposal
    made with `make_proposal` folds into a plan of one, so nothing that
    reads this has to know which command made it.

    `execution_id` and `step_id` are None until a run is
    recorded against this proposal, and are what say whether it is still
    open. Two fields rather than one, because a step is an entity inside
    the Execution aggregate rather than a stream of its own, so the root
    is what makes the step findable and checkable. `Dataset` carries the
    same pair for the same reason, and the root comes first there too.

    For an adopted plan of several runs the step is the first of them.
    The execution adoption dispatched holds one step per run in the order
    they were proposed, so the step where the work begins is the one the
    rest follow from, and naming every step here would be a copy of the
    execution's own list.

    Both nullable and never one without the other. They are written by
    one arm of the fold, from one event that carries both, so a state
    where only one is set is not reachable and nothing here defends
    against it.
    """

    id: UUID
    actor_id: UUID
    runs: tuple[ProposedRun, ...]
    status: ProposalStatus = ProposalStatus.OPEN
    execution_id: UUID | None = None
    step_id: UUID | None = None

    @property
    def sole_run(self) -> ProposedRun | None:
        """The run, when the proposal puts forward exactly one, and None for a plan of several.

        What a reader asks before treating a proposal as one run of one
        operation: taking it, or showing the operation and values a
        proposal of one has always shown. A property rather than a check
        at each call site, so the rule for when a proposal is one run is
        written once.
        """
        return self.runs[0] if len(self.runs) == 1 else None

    @property
    def is_taken(self) -> bool:
        """Whether anything has come of this proposal, either way.

        True for an adoption as well as for a take, because what this
        answers is whether the proposal is still open and both close it.
        The word is the one the read side has always used for that bit
        and is left alone; which of the two closed it is the status's to
        say.

        A property rather than a stored flag, for the reason an
        execution's status is derived: a field a writer can set is a
        field a writer can set wrong, and this one cannot disagree with
        the join it reads.

        Reads `execution_id` and not `step_id`, arbitrarily, because the
        two arrive together. The root is named because it is the one a
        reader can follow on its own.
        """
        return self.execution_id is not None


__all__ = [
    "PROPOSAL_MAX_RUNS",
    "InvalidProposalParametersError",
    "InvalidProposalRunsError",
    "Proposal",
    "ProposalAlreadyExistsError",
    "ProposalCannotBeAdoptedError",
    "ProposalCannotBeTakenError",
    "ProposalNotFoundError",
    "ProposalStatus",
    "ProposedRun",
]
