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

Five values, two live and three terminal:

    Running     no ending reported, and no pause standing over it
    Paused      the engine reported it stopped and can carry on
    Completed   the engine reported it reached its own end
    Aborted     something outside it stopped it
    Failed      it broke

Three terminals rather than one with a reason beside it, because the
engine this system is built to hear from reports exactly these three and
a reader should not have to parse a string to recover a distinction the
source already drew. The three also split cleanly by who or what ended
the run: itself, someone else, or a fault. That is the question a later
reader actually asks.

Paused is the first status a run can leave. Every other edge on this
machine points one way, and a resume points back, so the status is not
monotonic and a reader cannot infer how many events a stream holds from
where it ended up. The stream still only grows; it is the derived value
that revisits a value it held before.

No transient states. There is no Completing or Aborting, because there is
no moment here where a command has arrived and its event has not: the
handler decides and appends in one call. Transients belong to a system
that waits, and this one does not yet.

Paused is not one of them. A transient is a state the system passes
through on its own; a paused run sits there until something reports that
it moved, and it may sit there for a week.

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

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step.

    The grammar used to carry the live-versus-ended split: one gerund
    against three past participles. `PAUSED` ends that, because a paused
    run has not ended and "Paused" is a past participle all the same. So
    the distinction moved to `is_terminal`, where it can be asked rather
    than inferred from the shape of a word.

    Nothing here says the run is running NOW. It says the stream has a
    genesis event and no terminal, which is a claim about what this
    system has been told, not about the world. A run whose engine died
    without anyone reporting it stays `RUNNING` here forever, and closing
    that needs something watching rather than another value. `PAUSED` is
    the same kind of claim: the engine said it paused, and nothing here
    has heard otherwise since.
    """

    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ABORTED = "Aborted"
    FAILED = "Failed"

    @property
    def is_terminal(self) -> bool:
        """Whether no further event can land on a run in this status.

        Written as a positive list of the terminals rather than as the
        complement of the live ones, because "terminal" is what the
        property is called and a reader should not have to invert it to
        answer the question it asks.

        `test_run_aggregate.py` pins this mapping for every member, so a
        sixth status added without deciding which group it joins fails
        there rather than defaulting to live and quietly letting an
        ending through.
        """
        return self in (RunStatus.COMPLETED, RunStatus.ABORTED, RunStatus.FAILED)


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


class RunCannotBePausedError(Exception):
    """A pause was reported for a run that is not running.

    Refused from the three terminals, and from `PAUSED` itself: a second
    pause with no resume between them is a report this system has nowhere
    to put, because the stream already says the run is stopped and the
    new row would not change that.

    Same shape as the three ending refusals, and per R6 in
    docs/reference/naming.md for the same reason: the verb in the class
    name is the diagnostic, and the status it carries is the fact the
    caller does not have.
    """

    def __init__(self, run_id: UUID, status: "RunStatus") -> None:
        super().__init__(f"Run {run_id} cannot be paused: it is already {status}")
        self.run_id = run_id
        self.status = status


class RunCannotBeResumedError(Exception):
    """A resume was reported for a run that is not paused.

    The mirror of `RunCannotBePausedError`. Refused from the terminals,
    and from `RUNNING`, where there is no pause to carry on from.

    The two are not symmetric in how likely they are. A duplicate pause
    is a redelivery; a resume against a running run usually means two
    reporters disagree about what the engine did, and the status on the
    refusal is what lets a caller tell those apart.
    """

    def __init__(self, run_id: UUID, status: "RunStatus") -> None:
        super().__init__(f"Run {run_id} cannot be resumed: it is already {status}")
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

        Asked by the three ending deciders and by the two that pause and
        resume, so the set of terminals is written once, on the status,
        rather than five times as a tuple each of them has to keep in
        step.

        A paused run has NOT ended. This used to read
        `status is not RUNNING`, which gave the same answer while Running
        was the only live status and became wrong the moment a second one
        existed. Left alone it would have refused every ending on a
        paused run, which is the run an operator is most likely to want
        to abort.
        """
        return self.status.is_terminal


__all__ = [
    "InvalidRunParametersError",
    "Run",
    "RunAlreadyExistsError",
    "RunCannotBeAbortedError",
    "RunCannotBeCompletedError",
    "RunCannotBeFailedError",
    "RunCannotBePausedError",
    "RunCannotBeResumedError",
    "RunNotFoundError",
    "RunStatus",
]
