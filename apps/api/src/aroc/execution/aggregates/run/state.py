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

## No status field yet

The whole point of a run is that it moves, and nothing here moves it. The
commands that end a run are not written, so a status would have one
reachable value, and a one-valued field says less than no field while
suggesting a lifecycle is being enforced.

It lands with the first command that ends a run, derived in the fold from
which event the stream carries rather than written onto any payload. The
same reasoning kept availability off the Actor until the switch existed,
and a status off the Plan until something retires one.

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
from typing import Any
from uuid import UUID

from aroc.shared.identifier import Identifier


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
    """

    id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: Identifier


__all__ = [
    "InvalidRunParametersError",
    "Run",
    "RunAlreadyExistsError",
    "RunNotFoundError",
]
