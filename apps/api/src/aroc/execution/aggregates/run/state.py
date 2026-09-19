"""Run state and its domain errors.

A Run is one execution of a plan, as this system came to know about it.

## Reported, which is what the aggregate holds today

An engine ran the routine, and afterwards this system was told that it
did. Told, not observed: nothing here was present for the act, so the
record is secondhand by construction and the word says so. A run's record
is therefore a reference outward plus the facts that make it
interpretable: which plan was run, with what parameters, and what the
engine that ran it calls the result.

`external_ref` is required, not optional, and that is the invariant the
reported shape rests on. A run this system cannot point back at is a
claim that something happened somewhere, with no way to check it or to
find the data it produced. Refusing it costs a caller one field and buys
every later reader the ability to follow the record to its source.

## The status, and where it comes from

`status` is not on any payload. It is derived in the fold from which
event the stream carries, which is the only way to keep the two from
disagreeing: a status written onto an event could contradict the event it
rode in on, and the fold would have to pick a winner.

Four values, one running and three terminal:

    Running     the genesis event and nothing since
    Completed   the engine reported it reached its own end
    Aborted     something outside it stopped it
    Failed      it broke

Three terminals rather than one with a reason beside it, because the
engine this system is built to hear from reports exactly these three and
a reader should not have to parse a string to recover a distinction the
source already drew. The three also split cleanly by who or what ended
the run: itself, someone else, or a fault. That is the question a later
reader actually asks.

No transient states. There is no Completing or Aborting, because there is
no moment here where a command has arrived and its event has not: the
handler decides and appends in one call. Transients belong to a system
that waits, and this one does not yet.

Nothing carries a reason. A free-text reason is the field most likely to
end up holding something about a person, in the one table that cannot be
edited, and a failure message from an engine is exactly that kind of
text. `ActorDeactivated` carries no reason for the same reason, and this
follows it rather than inventing an exception.

## No field saying who drove the act, and there is not going to be one

Every run here is reported, because reporting one is the only way to
make one. When conducting lands it brings its own genesis event rather
than a flag on this one, so which of the two opened a stream is what
says who drove the act.

That is a field that cannot be set wrong, because it is not a field. A
run this system was told about has no way to describe itself as one this
system performed.

## Two runs can name the same external run, and nothing stops that

Nothing enforces that `external_ref` is unique across streams, so
recording the same engine run twice makes two records of it. An event
sourced aggregate has no consistency boundary spanning its siblings, so
closing this needs one of the two cross-stream patterns in
docs/reference/patterns.md, and both are decisions with consequences: a
derived stream id freezes a namespace forever, and a unique index needs a
projection nothing has built.

The gap is real and it is not urgent, because the only caller today is a
person or a script making one call. It becomes urgent with the first
adapter that retries, since a redelivered start is exactly the duplicate
this does not catch. That adapter is the trigger, and it is the right
place to decide, because it is the first thing that knows what the
natural key actually is.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from aroc.shared.identifier import Identifier


class RunStatus(StrEnum):
    """Where a run has got to.

    `RUNNING` is a gerund and the three terminals are past participles,
    which is the distinction the names are carrying: one describes an act
    still under way, the three describe one that is over. Values are
    PascalCase strings so a log line or a response body reads without a
    mapping step.

    Nothing here says the run is running NOW. It says the stream has a
    genesis event and no terminal, which is a claim about what this
    system has been told, not about the world. A run whose engine died
    without anyone reporting it stays `RUNNING` here forever, and closing
    that needs something watching rather than a fifth value.
    """

    RUNNING = "Running"
    COMPLETED = "Completed"
    ABORTED = "Aborted"
    FAILED = "Failed"


class InvalidRunParametersError(ValueError):
    """The parameters do not satisfy the schema the plan declares.

    Carries the reason the shared validator gave, which names the field
    and the constraint it failed. The message is the caller's only guide
    to fixing the values they sent, so it is passed through rather than
    replaced with a generic line.
    """


class RunNotFoundError(Exception):
    """A query named a run id with no stream behind it."""

    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"Run {run_id} not found")
        self.run_id = run_id


class RunAlreadyExistsError(Exception):
    """Recording was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a recording handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming it,
    and so a caller supplying its own id is refused instead of writing a
    second genesis event onto a live stream.

    Distinct from recording the same EXTERNAL run twice, which is not
    refused at all. See the module docstring.
    """

    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"Run {run_id} already exists")
        self.run_id = run_id


class RunCannotBeCompletedError(Exception):
    """Completion was asked for on a run that has already ended.

    One class per verb rather than one shared transition error, per R6 in
    docs/reference/naming.md. All three refuse from the same state, so a
    shared class is tempting, and the verb in the name is the diagnostic:
    a 409 mapping keys off `isinstance` rather than a string field, and a
    reader of a log line learns which ending was attempted without
    looking anything up.

    Carries the status the run is actually in, because that is the one
    fact the caller does not have. Knowing a run already ended is less
    useful than knowing it ended by being aborted.
    """

    def __init__(self, run_id: UUID, status: "RunStatus") -> None:
        super().__init__(f"Run {run_id} cannot be completed: it is already {status}")
        self.run_id = run_id
        self.status = status


class RunCannotBeAbortedError(Exception):
    """Abortion was asked for on a run that has already ended.

    The sibling of `RunCannotBeCompletedError`, refused for the same
    reason and kept apart for the same one.
    """

    def __init__(self, run_id: UUID, status: "RunStatus") -> None:
        super().__init__(f"Run {run_id} cannot be aborted: it is already {status}")
        self.run_id = run_id
        self.status = status


class RunCannotBeFailedError(Exception):
    """A failure was reported for a run that has already ended.

    Named for the verb like its two siblings, which costs this one some
    grace: "cannot be failed" is not something anybody says out loud. The
    alternative is breaking a family of three so one member reads better
    on its own, and a family a reader can predict is worth more than a
    sentence that scans.
    """

    def __init__(self, run_id: UUID, status: "RunStatus") -> None:
        super().__init__(f"Run {run_id} cannot be failed: it is already {status}")
        self.run_id = run_id
        self.status = status


@dataclass(frozen=True)
class Run:
    """One execution of a plan, as the fold leaves it.

    `plan_id` is a reference to a sibling stream in this same context, not
    a copy of it. What the plan said at the time is not carried here: the
    parameters were checked against that schema once, when the record was
    written, and the event says which plan was read to check them.

    `parameters` is the values the run was given. They conformed to the
    plan's schema at the moment they were recorded, and re-reading the
    plan later may find a different schema, which does not make this
    record wrong. It makes it a record of what was run.

    `external_ref` is what the engine that ran this calls it, as an
    open-scheme pair. The scheme names the engine's own identifier
    vocabulary and is not a closed set here, because which engine a
    deployment runs is a deployment's fact.

    `status` is the only field the fold computes rather than copies. See
    the module docstring for why it is derived from the event type and
    not read off a payload.
    """

    id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: Identifier
    status: RunStatus

    @property
    def has_ended(self) -> bool:
        """Whether a terminal event has landed on this stream.

        Asked by all three ending deciders, so the set of terminals is
        written once here rather than three times as a tuple each of them
        has to keep in step. A fourth terminal becomes one edit, and a
        decider that forgot to learn about it is not a thing that can
        happen.
        """
        return self.status is not RunStatus.RUNNING


__all__ = [
    "InvalidRunParametersError",
    "Run",
    "RunAlreadyExistsError",
    "RunCannotBeAbortedError",
    "RunCannotBeCompletedError",
    "RunCannotBeFailedError",
    "RunNotFoundError",
    "RunStatus",
]
