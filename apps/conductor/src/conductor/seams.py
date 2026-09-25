"""The three outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which control
library and which acquisition engine a deployment runs is a choice it
makes at its entrypoint. That is the same arrangement `apps/reporter` uses
for a store, and the reason is the same: a beamline runs what it runs, and
a package that named one would be holding an opinion a deployment owns.

None of the Protocols carries a `Port` suffix. Everything in this module is a
seam, so saying so distinguishes nothing, and `apps/api` forbids the
suffix for that reason.

## Why acquisition returns what the engine said, unmapped

`spikes/conductor/FINDINGS.md` drove four collisions into a real scan and
every one of them ended `exit_status: "success"`, including a six-point
scan that took four of its readings at one position. So an engine's word
for how a run ended is a claim this system was given, not a fact it
checked, and a seam that turned `success` into a boolean here would be
laundering the claim into a conclusion one layer before anyone could see
it. The word travels verbatim and something further out decides.

## Why recording is a seam and not a call

Two of these seams make something happen and the third makes something
known. Saying it out loud would be easier than routing it through a
Protocol, and it is routed anyway, because the core of this package
imports the standard library and itself and a test holds it there. The
client with the most reason to reach out directly is the one that can
least afford to.

It also leaves the degraded case where it belongs. Whether a walk may
carry on while nothing can be told about it is a question about which
adapter a deployment installs, and an adapter that means to carry on
handles its own outage. Nothing in `conduct` catches a recording
failure, so an adapter that raises stops the walk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.outcomes import Outcome
    from conductor.procedure import Procedure


@dataclass(frozen=True, slots=True)
class Citation:
    """Which execution and which of its steps an acquisition is running.

    AROC's own ids, carried out to the engine so that whatever watches
    that engine can say what a run belonged to. A bare RunEngine copies
    the keyword arguments of its call into the start document unchanged,
    which is what `spikes/conductor/FINDINGS.md` section 7 established,
    so metadata is a channel a driver can rely on.

    This replaced a reference this conductor minted for itself. That
    name was invented here because there was nothing better to carry: no
    execution existed before a walk began, so the only identity available
    was one the walk made up. AROC composes and dispatches the work now,
    so both ids exist before an engine is asked for anything, and putting
    a made-up third name in their place would be putting something into a
    permanent record that names nothing.

    Both travel or neither does. The reporter reads the pair and treats
    either one missing as a scan somebody ran by hand, so an engine given
    one key and not the other produces a record that looks deliberate and
    is wrong.
    """

    execution_id: str
    step_id: str


@dataclass(frozen=True, slots=True)
class Acquired:
    """What came back from asking an engine to run something.

    `engine_reference` is the name that joins. A reporter watching the
    same engine records its runs under the engine's own name for them, so
    that is what AROC can be asked for later, and
    `docs/reference/client-contract.md` holds both halves of that
    agreement. It is optional because not every engine has a name to
    give, and because a plan that opened no run has nothing to be named.

    `cites` is what the engine's own record says the run belonged to,
    read back out rather than echoed, which is what gives the check below
    something real to compare. It is not the join: it is how a person
    reading a data catalogue finds the execution a run came from, and how
    a reporter watching the engine knows which step to report against.

    `None` means no AROC ids came back, which happens two ways and both
    are ordinary: a walk outside any dispatch has none to carry, and a
    plan that opened no run recorded nothing to carry them in.
    """

    cites: Citation | None
    engine_reference: str | None
    said: str


class ReferenceNotCarriedError(RuntimeError):
    """An engine recorded AROC ids other than the ones it was given.

    An adapter is expected to read these back out of what the engine
    recorded rather than echo the argument it was handed, so a mismatch
    means the engine dropped them on the way through. That matters even
    though the join runs on `engine_reference`: a reporter watching the
    engine reads the pair off the start document to know which step a run
    belongs to, and a run missing them is one it treats as hand-run and
    files nowhere. The walk would report `Done` for every step regardless,
    which is the shape of failure this package exists to refuse.

    It costs one comparison here and cannot be caught at all afterwards,
    because by then the only record of what should have been carried is
    the one that did not carry it.
    """

    def __init__(self, *, plan: str, asked: Citation | None, got: Citation | None) -> None:
        self.plan = plan
        self.asked = asked
        self.got = got
        super().__init__(
            f"the acquisition of {plan!r} was given {asked} and came back with "
            f"{got}, so nothing watching that engine can say which step the run was"
        )


@runtime_checkable
class Control(Protocol):
    """Reading and writing one record at a time, underneath any engine."""

    def move(self, record: str, value: float) -> None:
        """Send a record to a value and return when it is there."""
        ...

    def read(self, record: str) -> float:
        """Read a record now."""
        ...


@runtime_checkable
class Acquisition(Protocol):
    """Asking an engine to run a routine, and hearing how it went."""

    def acquire(
        self, plan: str, parameters: Mapping[str, object], cites: Citation | None
    ) -> Acquired:
        """Run a plan, carrying AROC's ids so the run can be attributed later.

        `cites` is `None` for a procedure walked outside any dispatch,
        and an adapter given none must write no AROC keys at all rather
        than invent values for them. A run carrying ids that name nothing
        is worse than one carrying none: the first is read as a report
        this system is owed and the second as work somebody ran by hand,
        which is what it was.
        """
        ...


@dataclass(frozen=True, slots=True)
class Assignment:
    """One execution AROC dispatched, in terms this package can walk.

    What `Aroc.take` hands back. The ids are AROC's and the procedure is
    this package's own type, because `conduct` takes one of those and an
    assignment that needed translating at the call site would push
    AROC's shapes into the core.

    `step_ids` is index-aligned with `procedure.steps`, and the
    correspondence is positional because a `Procedure` here has no ids
    to key on. That is safe in a way the same shape was not inside AROC:
    both halves are built in one adapter, from one response, in one
    pass. There is no second writer and no later edit for them to drift
    across.

    The ids are needed even though a step is reported by index, because
    an acquisition carries them into the engine's own metadata so
    whatever watches that engine can say which step a run belonged to.
    `AROC_METADATA_KEYS` in `apps/reporter` is the other half.
    """

    execution_id: str
    procedure: Procedure
    step_ids: Sequence[str]


@runtime_checkable
class Aroc(Protocol):
    """Asking AROC for work, and telling it how the work went.

    The seam that replaced `Recording`, and the replacement is not a
    rename. That Protocol was written when a walk opened its own record:
    it began by announcing a reference it had minted, a procedure name
    and a step list, all three of which AROC now writes before anything
    is asked to drive them.

    So this asks rather than announces. AROC composes the procedure,
    dispatches the execution and holds the record; a conductor finds out
    what is waiting for it, says it is driving one, and reports each
    step against a record that already exists.

    ## Every call goes out, and none comes in

    A conductor dials AROC and AROC never dials back. That is measured
    rather than preferred: `beamlines/EXPANSION.md` establishes a
    beamline reaching a central host and not the reverse, and it stays
    the shape even where the reverse is reachable, because the
    alternative is an inbound port and a second credential at every
    beamline so that AROC can authenticate to a thing that moves motors.

    ## Waiting is not polling

    `take` is a long poll: it is given how long it may block and returns
    the moment work appears or the wait runs out. An idle conductor
    holds one connection rather than asking every few seconds, and a
    dispatch reaches it in milliseconds. `wait` is a socket bound, not a
    latency budget: returning nothing means nothing arrived in that
    window, never that there is none, and the caller asks again.

    ## Claiming is how two conductors stay apart

    Nothing reserves an assignment for whoever read it. Two conductors
    seeing one execution is expected, and `claim` is what settles it:
    exactly one gets True. An adapter must not treat False as a failure,
    because it is the ordinary outcome of a race that had to happen
    somewhere.

    A claim is also a write with nothing to undo it, so a conductor that
    claims work belonging to another beamline has driven hardware it
    does not own. That is why `take` is given a beamline rather than
    filtering afterwards.
    """

    def take(self, beamline: str, wait: float) -> Assignment | None:
        """Ask for one execution dispatched to this beamline and unclaimed.

        Blocks for up to `wait` seconds. None means nothing arrived in
        that window, which is most of what an idle beamline gets, and is
        not an error.
        """
        ...

    def claim(self, execution_id: str) -> bool:
        """Say this conductor is driving that execution.

        False means something else claimed it first, which is ordinary.
        True means it is this conductor's to walk.
        """
        ...

    def report(self, execution_id: str, index: int, outcome: Outcome) -> None:
        """Say how the step at that index ended.

        By index rather than by id, which is what AROC's step report
        takes: the step list is fixed at dispatch, so a position is
        unambiguous for the life of the record.

        This is the driver's account and only the driver's. What the
        engine says about the run an acquisition opened arrives at AROC
        from whatever watches that engine, on its own schedule, and the
        two are allowed to disagree.
        """
        ...

    def finish(self, execution_id: str) -> None:
        """Say nothing further is coming for that execution.

        Sent whether the walk ran out of steps or stopped at a failure.
        An execution left open is indistinguishable from one whose
        driver died, and the difference is worth recording.
        """
        ...


@runtime_checkable
class Reporting(Protocol):
    """Where one walk's outcomes go, already bound to its execution.

    What `conduct` takes, where the loop around it takes the whole `Aroc`
    seam. A walk reports and finishes; it does not ask for work and does
    not claim any, so handing it a port that could would be handing it
    two verbs it must never call. `reports_to` in `conduct` is the
    binding that turns the one into the other.

    Neither method names an execution, because a walk is of exactly one
    and whatever built this knows which. An index is enough to say which
    step, since the step list is fixed at dispatch.

    Two methods, where the seam this replaced had three. A walk no
    longer announces itself on the way in: it used to report its
    reference, its procedure name and its whole step list, and AROC
    writes all three at dispatch before anything is asked to drive them.
    """

    def step_ended(self, index: int, outcome: Outcome) -> None:
        """Say how the step at that index ended."""
        ...

    def walk_ended(self) -> None:
        """Say nothing further is coming."""
        ...
