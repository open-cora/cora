"""An engine seam over TomoScan, driven entirely over Channel Access.

TomoScan is not bluesky and the difference is the whole of this module. A
RunEngine is an object in the conductor's own process that publishes
documents; TomoScan is a service on the control network with a state
machine exposed as records. So where `bluesky_engine` imports nothing and
calls a callable, this one connects to an address and writes to it.

    written in         the two keeper ids, and the scan's parameters
    read back          the same two ids, out of the records
    engine reference   the file TomoScan says it wrote

## The citation has to be cleared, not merely left unwritten

`Running.run` says an adapter given no citation must write no keys rather
than invent values. Obeying that literally here would be a bug. A record
holds its last value, so a scan run with no citation after one that had
ids would read those ids back and claim to belong to a step it had
nothing to do with. Metadata on a plan call cannot do that, because it is
built fresh for every call and a record is not.

So no citation means the two records are emptied, which is the same
statement in a medium that remembers. The rule is about what the engine
ends up recording, and only the bluesky version of it is satisfied by
doing nothing.

## What the routine name is for

Nothing is dispatched by it. TomoScan performs one kind of scan and what
varies between runs is the parameters, so a routine name selects nothing
and is instead checked against the set this engine was told it may run.
That turns a mistyped or unexpected operation into a refusal before
anything is written, rather than into a scan with somebody else's
settings. A deployment naming several scan types wants a mapping here,
which is a change to this adapter and not to the seam.

## Why it waits for the scan twice

Starting is asynchronous: writing the start record returns before the
server has picked it up, so a single wait for completion would see a scan
that has not begun, find the state still idle, and call it finished. The
wait is therefore for the state to leave idle first and to return second.
An engine that never leaves idle is a refusal rather than a success.

## What it refuses

A server that is not running, before anything is written. Writing scan
parameters into a stopped IOC leaves settings behind that the next person
to press start would inherit, and this package should not be the reason a
beamline runs somebody else's exposure time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Final

import epics

from conductor.seams import Citation, Ran, ReferenceNotCarriedError

if TYPE_CHECKING:
    from collections.abc import Mapping

SERVER_RUNNING: Final = "ServerRunning"
START_SCAN: Final = "StartScan"
SCAN_STATUS: Final = "ScanStatus"
FULL_FILE_NAME: Final = "FullFileName"
EXECUTION_ID: Final = "KeeperExecutionId"
STEP_ID: Final = "KeeperStepId"
"""The records this adapter knows by name.

The last two are not TomoScan's own. They are added by a deployment so the
keeper's ids reach the data file, which is what lets a reporter watching
the same server say which step a scan belonged to, and what lets a person
holding the file find the work that made it.
"""

RUNNING_VALUE: Final = "Running"
IDLE_VALUE: Final = "Done"

POSIX_FILE: Final = "posix-file"
"""The vocabulary a TomoScan server's references belong to.

Its reference is the path of the file it just wrote, so it is an address
and not a name: nothing has to be asked where the data is, because the
engine already said. That is what a conductor driving this can file
directly, and what a reporter watching it must not try to resolve.

The word is a deployment's to agree on rather than a standard, and it
belongs with the other scheme this system records. A reporter pointed at
a Tiled store writes tiled-node-path for the same reason and by the same
agreement.
"""

CLEARED: Final = " "
"""What is written to a citation record when there is no citation.

A single space rather than the empty string, and this is the difference
between clearing a record and believing you did. These are character
waveforms, so an empty string is a write of zero elements, which the
server accepts and ignores: the record keeps the last scan's ids and a
reporter reads them off the next scan as though they were its own.

Measured against caproto, where put("") leaves a uuid in place and
put(" ") clears it. A space reads back as the empty string, so nothing
downstream has to know this happened.
"""


class EngineError(RuntimeError):
    """An engine that could not be asked to run anything."""


class UnreachableEngineError(EngineError):
    """Nothing answered at the prefix this engine was pointed at.

    `started` separates two situations that read alike in a log and want
    opposite responses. A server that never answered means nothing was
    asked of the station and nobody need go and look. A server that
    stopped answering after the start was written means a scan was begun
    and is now out of sight, so whatever it was driving may still be
    moving. Saying the first when the second happened is the error worth
    engineering against, because it tells somebody to do nothing.
    """

    def __init__(self, record: str, *, started: bool = False) -> None:
        self.record = record
        self.started = started
        if started:
            super().__init__(
                f"nothing answered at {record!r} after the scan had been started, "
                "so whether it is still running is unknown"
            )
        else:
            super().__init__(f"nothing answered at {record!r}, so no scan was started")


class EngineNotRunningError(EngineError):
    """The server is reachable and is not accepting scans."""

    def __init__(self, record: str, said: str) -> None:
        self.record = record
        self.said = said
        super().__init__(
            f"{record} says {said!r} rather than {RUNNING_VALUE!r}, "
            "so nothing was written and no scan was started"
        )


class ScanDidNotStartError(EngineError):
    """The start was written and the server stayed idle."""

    def __init__(self, routine: str, waited: float) -> None:
        self.routine = routine
        self.waited = waited
        super().__init__(
            f"{routine!r} was started and the engine was still idle "
            f"after {waited}s, so nothing can be said about how it went"
        )


class ScanDidNotFinishError(EngineError):
    """The scan began and was still going when the wait ran out."""

    def __init__(self, routine: str, waited: float) -> None:
        self.routine = routine
        self.waited = waited
        super().__init__(
            f"{routine!r} was still running after {waited}s; it has not been "
            "stopped, and whether it finishes is now a question for the beamline"
        )


class UnknownRoutineError(EngineError):
    """A routine this engine was not told it may run."""

    def __init__(self, routine: str, known: frozenset[str]) -> None:
        self.routine = routine
        self.known = known
        listed = ", ".join(sorted(known)) or "nothing"
        super().__init__(f"this engine runs {listed}, and was asked for {routine!r}")


@dataclass
class TomoscanEngine:
    """Runs one scan on one TomoScan server, and reads the join back out."""

    reference_scheme: ClassVar[str | None] = POSIX_FILE
    """A TomoScan server answers with a path, so its runs need no resolving.

    Declared as the seam declares it rather than narrowed to `str`. A
    class variable is mutable and therefore invariant, so an engine
    promising less than the seam does is one no deployment can use.
    """

    prefix: str
    routines: frozenset[str]
    connect_timeout: float = 5.0
    start_timeout: float = 30.0
    scan_timeout: float = 3600.0
    poll_interval: float = 0.5

    _pvs: dict[str, epics.PV] = field(default_factory=dict[str, epics.PV], init=False)
    _started: bool = field(default=False, init=False)
    """Whether the start has been written for the run in progress.

    Set between connecting to the start record and writing it, because
    a connection that fails leaves nothing asked for while a write that
    does not come back may have begun a scan.
    """

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Set a scan up, start it, wait for it, and say what it recorded."""
        if routine not in self.routines:
            raise UnknownRoutineError(routine, self.routines)

        self._started = False
        self._refuse_if_not_running()

        # The citation before the parameters, and both before the start, so
        # that a scan is never running with ids from the run before it.
        self._write_citation(cites)
        for name, value in parameters.items():
            self._required(name).put(value, wait=True)

        # What the engine had produced before being asked, so that whether
        # it ran can be decided from evidence afterwards rather than from
        # catching it in the act. See the module docstring.
        before = (self._text(SCAN_STATUS), self._text(FULL_FILE_NAME))

        # The scan's budget, not pyepics' thirty second default. A busy
        # record holds this write open until the scan ends, so the default
        # would abandon the wait on any scan longer than half a minute.
        start = self._required(START_SCAN)
        self._started = True
        start.put(1, wait=True, timeout=self.scan_timeout)
        self._await_started(before, limit=self.start_timeout, routine=routine)
        self._await_state(leaving=False, limit=self.scan_timeout, routine=routine)

        recorded = self._read_citation()
        if recorded != cites:
            raise ReferenceNotCarriedError(routine=routine, asked=cites, got=recorded)

        return Ran(
            cites=recorded,
            engine_reference=self._text(FULL_FILE_NAME) or None,
            said=self._text(SCAN_STATUS),
        )

    def _refuse_if_not_running(self) -> None:
        said = self._text(SERVER_RUNNING)
        if said != RUNNING_VALUE:
            raise EngineNotRunningError(self._name(SERVER_RUNNING), said)

    def _write_citation(self, cites: Citation | None) -> None:
        """Both ids, or two empty records. See the module docstring."""
        execution = cites.execution_id if cites else CLEARED
        step = cites.step_id if cites else CLEARED
        self._required(EXECUTION_ID).put(execution, wait=True)
        self._required(STEP_ID).put(step, wait=True)

    def _read_citation(self) -> Citation | None:
        execution, step = self._text(EXECUTION_ID), self._text(STEP_ID)
        if not execution and not step:
            return None
        return Citation(execution_id=execution, step_id=step)

    def _await_started(self, before: tuple[str, str], *, limit: float, routine: str) -> None:
        """Wait for the engine's own output to move, which is what starting looks like.

        Not for the busy record to leave idle, because against a real
        TomoScan there is no moment at which a client can see that. Its
        StartScan is a busy record, so the write is held open until the
        scan ends and the state has already come back by the time the
        caller regains control. Waiting for that edge passed here only
        because pyepics answers a get from a monitor cache that was
        measured running fifty milliseconds behind, which is luck rather
        than a design and would have failed on a loaded host.

        What both kinds of server have in common is that a scan which
        happened leaves different output behind than the scan before it.
        So this waits for that, and a server holding the write open
        satisfies it on the first look.

        The assumption is that a scan changes its status or its file
        name. TomoScan numbers its files, so ordinarily both move. A
        station configured to overwrite one file could produce a scan
        this cannot see, and would be reported as never having started.
        """
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if (self._text(SCAN_STATUS), self._text(FULL_FILE_NAME)) != before:
                return
            time.sleep(self.poll_interval)
        raise ScanDidNotStartError(routine, limit)

    def _await_state(self, *, leaving: bool, limit: float, routine: str) -> None:
        """Wait for the engine to come back to idle.

        `leaving` is kept so a caller has to say which edge it means, and
        the start edge is refused rather than silently waited for. There
        is no start edge to wait for: a busy record holds the write open
        until the scan ends, so by the time a client can look, the scan
        it started is already over.
        """
        if leaving:
            raise ScanDidNotStartError(routine, limit)
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if self._text(START_SCAN) == IDLE_VALUE:
                return
            time.sleep(self.poll_interval)
        raise ScanDidNotFinishError(routine, limit)

    def _name(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}"

    def _text(self, suffix: str) -> str:
        """One record as a string, read from the server rather than a cache.

        `as_string` matters rather than being tidy: several of these are
        character waveforms, and reading one without it gives an array of
        integers that compares equal to nothing.

        `use_monitor=False` matters more. pyepics answers a get from the
        last value a monitor delivered, and that value was measured
        running fifty milliseconds behind the server immediately after a
        put returns. Every decision in this module is about what the
        engine is doing now, and fifty milliseconds is long enough to
        decide it wrongly.
        """
        value = self._required(suffix).get(as_string=True, use_monitor=False)
        return "" if value is None else str(value)

    def _required(self, suffix: str) -> epics.PV:
        name = self._name(suffix)
        pv = self._pvs.get(name)
        if pv is None:
            pv = epics.PV(name, connection_timeout=self.connect_timeout)
            self._pvs[name] = pv
        if not pv.wait_for_connection(timeout=self.connect_timeout):
            raise UnreachableEngineError(name, started=self._started)
        return pv

    def close(self) -> None:
        """Drop every connection this engine opened."""
        for pv in self._pvs.values():
            pv.disconnect()
        self._pvs.clear()


__all__ = [
    "EngineError",
    "EngineNotRunningError",
    "ScanDidNotFinishError",
    "ScanDidNotStartError",
    "TomoscanEngine",
    "UnknownRoutineError",
    "UnreachableEngineError",
]
