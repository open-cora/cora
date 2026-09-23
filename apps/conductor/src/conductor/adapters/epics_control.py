"""A control seam over Channel Access, which checks that a move arrived.

The obvious implementation of `Control.move` is a put that waits, and it
would be wrong here in a way the rest of this package exists to prevent.
`spikes/conductor/FINDINGS.md` measured three ways a motor can fail to go
where it was sent while every layer above it reports success, and two of
them are reachable through a bare put:

  - A rival write to `.VAL` sends the motor somewhere else, and the
    completion that comes back belongs to the rival's move.
  - `.SPMG` set to Stop holds the motor, and every later move returns
    immediately having done nothing at all. The scan measured there
    finished six points in two seconds and reported success.

So this adapter refuses to move a motor that is being held, it waits for
the readback rather than for the put, it waits for the motion to stop,
and it says which of those failed.

## Why position alone was not enough

Waiting on `.RBV` was the first implementation and it let the `rival_move`
case straight through. A motor redirected past its target crosses the
tolerance window on the way, so a poll that looks only at position can
catch it in transit and call it arrival. Measured against the soft IOC,
a move to 3.0 with a rival redirecting to 9.0 mid-flight returned as
arrived at three of four deadbands, each time with `.DMOV` reading 0.
The conductor above would have released the claim and started the next
step against a motor that was still travelling.

Arrival is therefore two conditions, not one: the readback is close
enough, and the record says the motion has finished. `.DMOV` is read
before `.RBV` on each poll, so a reading taken to be final was taken
after the record said it had stopped. Nothing here can promise the motor
stays there, because a rival is free to start a new move the moment this
returns.

## What it does not do

It does not stop anything on the way out. There is no reliable hook for
that, which the orphan section of those findings demonstrates, and a
method here promising it would be the overclaim this package keeps
refusing.

It does not know that a record is a motor. `.SPMG`, `.RBV` and `.RDBD`
are motor-record fields, and a deployment driving a temperature setpoint
has none of them. Each is looked for once and remembered; a record that
does not serve one is moved and verified without it, and the reduced
guarantee is named in `Verified`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import epics

if TYPE_CHECKING:
    from collections.abc import Iterator

READBACK_FIELD: Final = "RBV"
"""Where a motor record reports where it actually is."""

DEADBAND_FIELD: Final = "RDBD"
"""How close a motor record considers close enough."""

DONE_MOVING_FIELD: Final = "DMOV"
"""Where a motor record says whether it has stopped."""

MOTION_IS_FINISHED: Final = 1
"""The value of the done-moving field that means the motor is at rest."""

HOLD_FIELD: Final = "SPMG"
"""Stop, Pause, Move or Go. Anything but Go means moves will not happen."""

MOVING_IS_PERMITTED: Final = "Go"
"""The one value of the hold field that lets a move happen."""


class ControlError(RuntimeError):
    """Something about a record stopped a move from being trusted."""


class UnreachableRecordError(ControlError):
    """The record did not connect, so nothing was written."""


class DeviceHeldError(ControlError):
    """The record is latched and would have accepted a move it never made.

    This is the `rival_hold` case from the findings, caught before the
    write rather than after: the scan measured there took four of its six
    readings at one position and reported success, because a held motor
    accepts every move instantly and performs none.
    """

    def __init__(self, record: str, holding: str) -> None:
        self.record = record
        self.holding = holding
        super().__init__(
            f"{record} is held at {holding!r} rather than {MOVING_IS_PERMITTED!r}, "
            "so a move would be accepted and not performed"
        )


class DidNotArriveError(ControlError):
    """The put completed and the readback never reached the target."""

    def __init__(self, record: str, asked: float, got: float, tolerance: float) -> None:
        self.record = record
        self.asked = asked
        self.got = got
        self.tolerance = tolerance
        super().__init__(
            f"{record} was sent to {asked} and reads {got}, "
            f"which is outside a tolerance of {tolerance}"
        )


class StillMovingError(ControlError):
    """The readback reached the target and the record never said it stopped.

    Distinct from `DidNotArriveError` because the two mean different
    things to whoever reads them: that one says the motor went somewhere
    else, this one says it is still going. A single error carrying a
    position inside tolerance and the word "did not arrive" would read as
    a contradiction.
    """

    def __init__(self, record: str, asked: float, got: float) -> None:
        self.record = record
        self.asked = asked
        self.got = got
        super().__init__(
            f"{record} was sent to {asked} and reads {got}, but "
            f".{DONE_MOVING_FIELD} still says it is moving"
        )


@dataclass(frozen=True, slots=True)
class Verified:
    """How thoroughly one move was checked, for a caller that wants to know.

    `against` names the field the arrival was confirmed on. When a record
    serves no readback the move is confirmed against the record itself,
    which proves the put landed and nothing more, and `readback` is False
    so that a reader is not misled about which of the two happened.

    `settled` says whether the record could confirm the motion had
    stopped. A setpoint serving no `.DMOV` cannot, and a position taken
    from one is a position at a moment rather than a resting place.
    """

    record: str
    asked: float
    got: float
    against: str
    readback: bool
    settled: bool


@dataclass(slots=True)
class EpicsControl:
    """Moves and reads single records, and verifies what it moved.

    `timeout` bounds the put. `settle` bounds how long the readback is
    given to catch up afterwards, which is a separate clock because a put
    can complete the instant a rival's move completes while the motor is
    still travelling. `tolerance` is the floor for what counts as
    arrived; a record serving a deadband raises it to that.
    """

    timeout: float = 30.0
    settle: float = 10.0
    tolerance: float = 1e-3
    connect_timeout: float = 2.0
    _pvs: dict[str, epics.PV] = field(default_factory=dict[str, epics.PV], init=False)
    _absent: set[str] = field(default_factory=set[str], init=False)
    _verified: list[Verified] = field(default_factory=list[Verified], init=False)

    @property
    def verified(self) -> list[Verified]:
        """Every move this adapter has confirmed, oldest first."""
        return list(self._verified)

    def move(self, record: str, value: float) -> None:
        """Send a record to a value, and return only once it is there and at rest."""
        target = self._required(record)
        self._refuse_if_held(record)

        written = target.put(value, wait=True, timeout=self.timeout)
        if written is None:
            raise UnreachableRecordError(f"writing {value} to {record} timed out")

        against, watcher = self._readback_for(record, target)
        done = self._optional(f"{record}.{DONE_MOVING_FIELD}")
        tolerance = self._tolerance_for(record)
        got, still_moving = self._wait_for_arrival(watcher, done, value, tolerance)
        if got is None or abs(got - value) > tolerance:
            raise DidNotArriveError(record, value, float("nan") if got is None else got, tolerance)
        if still_moving:
            raise StillMovingError(record, value, got)

        self._verified.append(
            Verified(
                record=record,
                asked=value,
                got=got,
                against=against,
                readback=against.endswith(READBACK_FIELD),
                settled=done is not None,
            )
        )

    def read(self, record: str) -> float:
        """Read a record now, preferring its readback where it serves one."""
        target = self._required(record)
        _, watcher = self._readback_for(record, target)
        value = watcher.get(timeout=self.connect_timeout)
        if value is None:
            raise UnreachableRecordError(f"reading {record} returned nothing")
        return float(value)

    def _wait_for_arrival(
        self, watcher: epics.PV, done: epics.PV | None, target: float, tolerance: float
    ) -> tuple[float | None, bool]:
        """Poll until the readback is close enough and the motion has stopped.

        Returns the last reading and whether the record still said it was
        moving, so that the caller can tell a motor that went elsewhere
        from one that has not finished going.

        The two conditions are read in this order deliberately. A motion
        flag sampled before the position means a reading accepted as
        final was taken after the record said it had stopped; the other
        order would accept a position sampled mid-flight and confirmed by
        a flag that had not caught up.

        Polling rather than a subscription because the question is
        whether a value settled, and a callback that fires on every tick
        of a five second move answers a different one.
        """
        deadline = time.monotonic() + self.settle
        latest: float | None = None
        while True:
            moving = self._is_moving(done)
            reading = watcher.get(timeout=self.connect_timeout)
            if reading is not None:
                latest = float(reading)
                if not moving and abs(latest - target) <= tolerance:
                    return latest, False
            if time.monotonic() >= deadline:
                return latest, moving
            time.sleep(0.05)

    def _is_moving(self, done: epics.PV | None) -> bool:
        """Whether the record says it is still in motion.

        A record serving no `.DMOV` cannot say, and is taken to be at
        rest. The alternative is refusing every move to a setpoint that
        is not a motor, and `Verified.settled` is False so that the
        weaker check is visible rather than assumed.
        """
        if done is None:
            return False
        reading = done.get(timeout=self.connect_timeout)
        return reading is not None and int(reading) != MOTION_IS_FINISHED

    def _refuse_if_held(self, record: str) -> None:
        """Refuse a move to a record whose hold field is not letting it move."""
        hold = self._optional(f"{record}.{HOLD_FIELD}")
        if hold is None:
            return
        holding = hold.get(as_string=True, timeout=self.connect_timeout)
        if holding is not None and holding != MOVING_IS_PERMITTED:
            raise DeviceHeldError(record, str(holding))

    def _readback_for(self, record: str, target: epics.PV) -> tuple[str, epics.PV]:
        """The field arrival is confirmed on, and a connection to it."""
        name = f"{record}.{READBACK_FIELD}"
        readback = self._optional(name)
        return (name, readback) if readback is not None else (record, target)

    def _tolerance_for(self, record: str) -> float:
        """The configured floor, raised to the record's own deadband."""
        deadband = self._optional(f"{record}.{DEADBAND_FIELD}")
        if deadband is None:
            return self.tolerance
        value = deadband.get(timeout=self.connect_timeout)
        return max(self.tolerance, float(value)) if value else self.tolerance

    def _required(self, name: str) -> epics.PV:
        """Connect, or say plainly that the record is not there."""
        pv = self._connect(name)
        if pv is None:
            raise UnreachableRecordError(f"{name} did not connect within {self.connect_timeout}s")
        return pv

    def _optional(self, name: str) -> epics.PV | None:
        """Connect to a field that may not exist, remembering when it does not."""
        if name in self._absent:
            return None
        pv = self._connect(name)
        if pv is None:
            self._absent.add(name)
        return pv

    def _connect(self, name: str) -> epics.PV | None:
        """One connection per name, kept for later moves."""
        existing = self._pvs.get(name)
        if existing is not None:
            return existing
        pv = epics.PV(name, connection_timeout=self.connect_timeout)
        if not pv.wait_for_connection(timeout=self.connect_timeout):
            return None
        self._pvs[name] = pv
        return pv

    def close(self) -> None:
        """Drop every connection. Moving again reconnects."""
        for pv in self._pvs.values():
            pv.disconnect()
        self._pvs.clear()
        self._absent.clear()

    def __enter__(self) -> EpicsControl:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def records_of(*names: str) -> Iterator[str]:
    """Yield each name with any field suffix removed.

    A convenience for turning a configured list into the records a claim
    would name, which is the same normalisation `Scope.record` performs.
    """
    for name in names:
        yield name.split(".", 1)[0]
