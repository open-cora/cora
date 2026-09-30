"""The five outward seams, named for what a conductor does through them.

A seam is a Protocol here and an adapter under `conductor.adapters`, so
which control library, which engine and which system of record a
deployment runs are choices it makes at its entrypoint.

None of the Protocols carries a Port suffix. Everything in this module is
a seam, so saying so distinguishes nothing, and `apps/keeper` forbids the
suffix for that reason.

## Named for the need, not for what answers it

Each name says what this package does through the seam. `Adjusting` puts
one value where a step says, `Running` hands a whole routine over,
`Tasking` gets work this beamline owns, `Reporting` says how that work
went, and `Filing` says where the data it produced is being kept.

A name that says what is on the other side cannot be wrong in a useful
way, because anything over there is a control system of some sort, or an
engine of some sort, or a record of some sort. A name that says what the
caller does through the seam can be wrong the moment the caller stops
doing it, which is the property worth having.

`Reporting` is the one that was already this, and it was arrived at
under pressure rather than designed: handing a walk the whole record
would have handed it two verbs it must never call. The other three are
that reasoning applied on purpose.

## Why claiming hands back the reporting

`Tasking.claim` returns a `Reporting` rather than a bool. A conductor
may report on an execution exactly when it has claimed that execution,
and a claim that hands back the means of reporting makes that structural
instead of a rule somebody follows. It also removes the step that used
to sit between them, where a caller took a record and an id and bound
the two itself: there is nothing left to get wrong, because the id never
passes through this package's hands.

`None` means another conductor got there first. That is the ordinary
outcome of a race that had to happen somewhere, and it is not an error.

## Why run returns what the engine said, unmapped

A scan can take a collision from a second writer and still end in the
engine's own word for success, including a six-point scan that takes four
of its readings at one position. So an engine's word for
how a run ended is a claim this system was given, not a fact it checked,
and a seam that turned `success` into a boolean here would be laundering
the claim into a conclusion one layer before anyone could see it. The
word travels verbatim and something further out decides.

## Why an index and not an id

`Reporting.step_ended` names a step by its place in the procedure, and
that is the step's identity rather than a convenience. A step has no id
of its own in the record this reports to: the position the dispatch
fixed is what identifies it, which `apps/keeper` states on the command
that takes it.

`Assignment` carries ids as well, and they are for something else
entirely. They travel out to the engine so that whatever watches that
engine can say which step a run belonged to, and they never come back
here as a way of naming one.

## Why a conductor files a dataset at all

`Filing` looks like somebody else's job, because it is one a reporter
also does. What decides which of them does it is not who is closer to
the data, it is what the engine handed back.

An engine that answers with a name has said nothing about where the
data is. Turning that name into an address needs the store, so
something holding the store has to do it, and that is what a reporter
is for. An engine that answers with a location has already given the
address, and a reporter asked to look that up would be resolving a
path as though it were a name, which no store can answer.

So this seam is here for the engines of the second kind, and
`Running.reference_scheme` is how an engine says which kind it is. A
deployment whose engine answers with names leaves this unwired and its
datasets arrive from whatever watches the store.

Nothing coordinates the two. A conductor cannot tell whether a reporter
covers its beamline and does not try: the seam is wired from what its
own engine returns, which is the only half of the question it can
answer without asking anybody.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.outcomes import Outcome
    from conductor.procedure import Procedure


@dataclass(frozen=True, slots=True)
class Citation:
    """Which execution and which of its steps a run belongs to.

    The record's own ids, carried out to the engine so that whatever
    watches that engine can say what a run belonged to. An engine that
    copies the call it was given into what it records is what makes that
    possible, so metadata is a channel a driver can rely on for such an
    engine.

    Both travel or neither does. A reporter reads the pair and treats
    either one missing as a run somebody started by hand, so an engine
    given one key and not the other produces a record that looks
    deliberate and is wrong.
    """

    execution_id: str
    step_id: str


@dataclass(frozen=True, slots=True)
class Ran:
    """What came back from asking an engine to run something.

    `engine_reference` is the name that joins. A reporter watching the
    same engine records its runs under the engine's own name for them,
    so that is what the record can be asked for later, and
    `docs/client-contract.md` holds both halves of that agreement. It is
    optional because not every engine has a name to give, and because a
    routine that opened no run has nothing to be named.

    What kind of name it is is not recorded here. It is the same for
    every run of one engine, so it sits on `Running.reference_scheme`
    where it can be read without driving anything.

    `cites` is what the engine's own record says the run belonged to,
    read back out rather than echoed, which is what gives the check
    below something real to compare. It is not the join: it is how a
    person reading a data catalogue finds the execution a run came from.

    `None` means no ids came back, which happens two ways and both are
    ordinary: a walk outside any dispatch has none to carry, and a
    routine that opened no run recorded nothing to carry them in.
    """

    cites: Citation | None
    engine_reference: str | None
    said: str


class ReferenceNotCarriedError(RuntimeError):
    """An engine recorded ids other than the ones it was given.

    An adapter is expected to read these back out of what the engine
    recorded rather than echo the argument it was handed, so a mismatch
    means the engine dropped them on the way through. That matters even
    though the join runs on `engine_reference`: a reporter watching the
    engine reads the pair out of what that engine recorded to know which
    step a run belongs to, and a run missing them is one it treats as
    started by hand and files nowhere. The walk would report `Done` for
    every step regardless, which is the shape of failure this package
    exists to refuse.

    It costs one comparison here and cannot be caught at all afterwards,
    because by then the only record of what should have been carried is
    the one that did not carry it.
    """

    def __init__(self, *, routine: str, asked: Citation | None, got: Citation | None) -> None:
        self.routine = routine
        self.asked = asked
        self.got = got
        super().__init__(
            f"the run of {routine!r} was given {asked} and came back with "
            f"{got}, so nothing watching that engine can say which step the run was"
        )


@dataclass(frozen=True, slots=True)
class Assignment:
    """One execution that was dispatched, in terms this package can walk.

    What `Tasking.take` hands back. The procedure is this package's own
    type, because `conduct` takes one of those and an assignment that
    needed translating at the call site would push the record's shapes
    into the core.

    `step_ids` is index-aligned with `procedure.steps`, and the
    correspondence is positional because a `Procedure` here has no ids to
    key on. Both halves are built in one adapter, in one pass, so there
    is no second writer and no later edit for them to drift across. Not
    from one response: the steps come from the procedure and their ids
    from the execution, because the two number their steps differently
    and only the execution's numbering is the one a report is keyed on.

    The ids are carried into the engine's own metadata so whatever
    watches that engine can say which step a run belonged to. They are
    not how a step is named when reporting: see the module docstring.
    """

    execution_id: str
    procedure: Procedure
    step_ids: Sequence[str]


@dataclass(frozen=True, slots=True)
class Address:
    """Where a run's data is, and the vocabulary that says how to read it.

    A pair rather than two arguments, because half of one is worse than
    neither: a value with no scheme cannot be resolved by anything, and
    a scheme with no value names a vocabulary and nothing in it. The two
    are built in one place, from the engine's answer and from the seam
    that produced it, so a caller has no way to supply one and not the
    other.

    `scheme` is not this package's to invent. It names an open
    vocabulary the record keeps as given, posix-file being what a
    beamline writing HDF5 to a filesystem has to say. The engine decides
    it, because the engine is what determines the kind of thing its
    references are.
    """

    scheme: str
    value: str


@runtime_checkable
class Adjusting(Protocol):
    """Putting one value where a step says, underneath any engine."""

    def set(self, record: str, value: float) -> None:
        """Send a record to a value and return when it is there."""
        ...


@runtime_checkable
class Running(Protocol):
    """Handing a whole routine to an engine, and hearing how it went."""

    reference_scheme: ClassVar[str | None]
    """The vocabulary this engine's references belong to, or `None`.

    `None` says a reference from this engine is a name, meaningless
    until something holding the store resolves it. A string says a
    reference is already an address in that vocabulary, and that
    nothing further has to happen for it to be worth recording.

    A fact about the engine and not about any one run, which is why it
    is here rather than on `Ran`. It has to be readable before anything
    has been driven: a deployment wired to file datasets and pointed at
    an engine that answers with names is misconfigured, and the moment
    to say so is while it is starting up rather than after the first
    scan of the day has finished and filed nothing.

    A class variable rather than an instance attribute, because the two
    kinds of engine are two kinds of thing rather than one thing with a
    setting. It also means a caller can ask a class what it would
    answer with, which is what makes the startup check cheap.
    """

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Run a routine, carrying the ids so the run can be attributed later.

        `cites` is `None` for a procedure walked outside any dispatch,
        and an adapter given none must write no keys at all rather than
        invent values for them. A run carrying ids that name nothing is
        worse than one carrying none: the first is read as a report this
        system is owed and the second as work somebody ran by hand,
        which is what it was.
        """
        ...


@runtime_checkable
class Reporting(Protocol):
    """Saying how one walk's steps ended, and that it is over.

    Bound to the execution being walked before it ever reaches a walk,
    so neither method names one. A walk is of exactly one execution and
    whatever handed this over knows which, which is what keeps `conduct`
    from being able to report against the wrong record.
    """

    def step_ended(self, index: int, outcome: Outcome) -> None:
        """Say how the step at that position ended.

        This is the driver's account and only the driver's. What the
        engine says about a run arrives from whatever watches that
        engine, on its own schedule, and the two are allowed to
        disagree.
        """
        ...

    def walk_ended(self) -> None:
        """Say nothing further is coming.

        Sent whether the walk ran out of steps or stopped at a failure.
        An execution left open is indistinguishable from one whose
        driver died, and the difference is worth recording.
        """
        ...


@runtime_checkable
class Tasking(Protocol):
    """Getting work this beamline owns, and the means to report on it.

    ## Every call goes out, and none comes in

    A conductor dials out and nothing dials back. That is measured
    rather than preferred: a survey of the beamlines this is pointed at
    found each one reaching a central host and not the reverse, and it
    stays the shape even where the reverse is reachable, because the
    alternative is an inbound port and a second credential at every
    beamline so that something can authenticate to a thing that moves
    motors.

    ## Waiting is not polling

    `take` is a long poll: it is given how long it may block and returns
    the moment work appears or the wait runs out. An idle conductor
    holds one connection rather than asking every few seconds, and a
    dispatch reaches it in milliseconds.
    """

    def take(self, beamline: str, wait: float) -> Assignment | None:
        """Ask for one execution dispatched to this beamline and unclaimed.

        Blocks for up to `wait` seconds. `None` means nothing arrived in
        that window, which is most of what an idle beamline gets, and is
        not an error. `wait` is a socket bound rather than a latency
        budget: nothing coming back never means there is none, and the
        caller asks again.

        Given a beamline rather than filtering afterwards, because a
        claim is a write with nothing to undo it and a conductor that
        claimed work belonging to another beamline has driven hardware
        it does not own.
        """
        ...

    def claim(self, execution_id: str) -> Reporting | None:
        """Take that execution, and get back the way to report on it.

        `None` means something else claimed it first, which is ordinary
        and not a failure: nothing reserves an assignment for whoever
        read it, two conductors seeing one execution is expected, and
        this is what settles it. Exactly one caller gets a `Reporting`.
        """
        ...


@runtime_checkable
class Filing(Protocol):
    """Recording where the data a run produced is being kept."""

    def record(self, cites: Citation, address: Address) -> None:
        """File one address against the step whose run produced it.

        Filing one address twice against one step is expected rather
        than exceptional. A conductor restarted mid-walk redoes the step
        it was in, and the address is the thing both attempts agree on,
        so whatever is on the other side is what has to turn the two
        into one record.

        Nothing comes back. A reporter's counterpart returns the id of
        the record it made, because a reporter goes on to use it; a
        conductor has nothing to do with one, and handing it a value it
        does not need is an invitation to start depending on it.

        `cites` is required and not optional, unlike everywhere else
        here that carries one. A dataset is filed against a step, so a
        walk with nothing to name has nothing to file, and the caller
        decides that before reaching this rather than passing `None`
        and asking the far side to work it out.
        """
        ...


__all__ = [
    "Address",
    "Adjusting",
    "Assignment",
    "Citation",
    "Filing",
    "Ran",
    "ReferenceNotCarriedError",
    "Reporting",
    "Running",
    "Tasking",
]
