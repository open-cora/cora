"""A TomoScan-shaped server that scans nothing, for commissioning a conductor.

The engine adapter drives records. This serves records of the same names
and the same types, runs a scan that takes a few seconds and moves no
hardware, and leaves behind the status, the file name and the two keeper
ids a reporter reads afterwards. A conductor pointed at this walks a real
procedure, claims real devices, writes real ids and produces a real
report, and the only thing that did not happen is the scan.

It exists because the alternative way to commission a conductor at a
beamline is to start a scan on somebody's sample.

## What it is faithful to, and how that was decided

Measured against 2-BM rather than copied from the documentation:

    ServerRunning   bi         ZNAM Stopped   ONAM Running
    StartScan       busy       ZNAM Done      ONAM Acquire
    ScanStatus      waveform   char
    FullFileName    waveform   char
    ScanUUID        stringout  VAL  Unknown

So the enum strings here are the ones a real client sees, and the two
text records are character waveforms rather than strings, which is what
makes a reader that forgot `as_string` fail here the way it would fail
there.

`busy` is a synApps record and this is not an IOC, so `StartScan` is an
enum whose write is held open for the duration of the scan. That is the
behaviour of a busy record rather than its type, and the behaviour is
the part an adapter can tell apart.

## What it is deliberately not

Not the test double in `tests/_tomoscan_ioc.py`, which carries switches
for provoking failures and is free to use whatever strings make a test
read well. This has no switches: a server that can be told to misbehave
is a server somebody will accidentally tell to misbehave. The two are
held to the same record names by `tests/test_tomoscan_sim.py`.

## The order the two late records are written in

A scan's identifier and its file name are both written once, and this
server writes each on the side of the idle edge that TomoScan writes it
on. That ordering is the whole reason a watcher can get either one
wrong, so a simulator that writes them in a convenient order is a
simulator that cannot fail where a beamline does.

    StartScan     Acquire        the scan begins
    ScanUUID      a fresh uuid   minted just after, so a reader that
                                 took the busy edge as its signal still
                                 sees the previous scan's identifier
    StartScan     Done           the scan ends
    FullFileName  the path       written just after, so a reader that
                                 took the idle edge as its signal still
                                 sees the previous scan's file

Measured by running TomoScan's own `begin_scan` and `end_scan`, imported
from the package rather than reimplemented, against a soft IOC that logs
every record write. This file had `FullFileName` on the other side of
the idle edge and so handed out the right answer to a client that asks
at the wrong moment.

`ScanUUID` is left standing between scans rather than blanked, which is
what upstream chose: the record is autosaved, so it survives an IOC
restart holding whatever the last scan put there. A reader therefore
cannot treat its contents as belonging to the current scan, and the only
sound signal is that the value changed.

Not a simulation of tomography. Nothing here models angles, exposure or
a detector. The parameters exist so that a procedure setting them is
exercised end to end, and they are written down and read back and
otherwise ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, run

IDLE = "Done"
BUSY = "Acquire"
"""What 2-BM's StartScan reads as, measured rather than assumed."""

SETTLE_SECONDS = 0.5
"""Idle for a moment after the write, before going busy.

A real server does not become busy in the same instant it is asked, and
an adapter that assumes it does passes against a server that is quicker
than the adapter and fails against one that is not.
"""

DEFAULT_SCAN_SECONDS = 6.0
"""How long a simulated scan takes, when nothing says otherwise.

Long enough that a person watching `caget` sees it happen, short enough
that commissioning is not spent waiting.
"""


def _text(value: str, size: int = 256) -> Any:
    """A character waveform, which is how TomoScan serves its strings."""
    return pvproperty(
        value=value,
        dtype=ChannelType.CHAR,
        max_length=size,
        string_encoding="utf-8",
    )


def station_of(prefix: str) -> str:
    """The part of a record prefix that differs between beamlines.

    The simulated file name was once a literal naming one station, so a
    second beamline running this simulator produced a byte-identical
    address, and a dataset address is the whole of how the record tells
    one run's data from another's. The first segment of the prefix is
    already unique per deployment, which is why nothing new has to be
    configured for the names to differ.
    """
    return prefix.split(":", 1)[0] or "corasim"


class TomoscanSim(PVGroup):
    """The records a conductor writes and a reporter reads, and no others."""

    Simulated = _text("cora: this server scans nothing and moves nothing")
    """Says what this is, to whoever finds it on the network and wonders.

    There is no counterpart on a real TomoScan, which is the point: its
    presence is how a reader tells the two apart without knowing which
    prefix is which.
    """

    ServerRunning = pvproperty(value="Running", dtype=ChannelType.STRING)
    ScanStatus = _text("Scan complete")
    FullFileName = _text("")

    ScanUUID = pvproperty(value="Unknown", dtype=ChannelType.STRING)
    """What the engine calls one run, fresh for every scan.

    A string rather than the character waveform the two records above
    are, because upstream declares it `stringout` while TomoScan's own
    text is waveforms. A uuid is 36 characters and a `stringout` holds
    40, which is why that choice works there and why copying the
    waveform shape here would stop this being a faithful stand-in.

    `Unknown` is upstream's initial value, and it is what a reader sees
    from a server that has not scanned since the record was created.
    """
    KeeperExecutionId = _text("")
    KeeperStepId = _text("")

    StartScan: Any = pvproperty(value=IDLE, enum_strings=[IDLE, BUSY], dtype=ChannelType.ENUM)

    NumAngles = pvproperty(value=1500, dtype=ChannelType.LONG)
    ExposureTime = pvproperty(value=0.1, dtype=ChannelType.DOUBLE)
    RotationStart = pvproperty(value=0.0, dtype=ChannelType.DOUBLE)
    RotationStep = pvproperty(value=0.12, dtype=ChannelType.DOUBLE)

    scan_seconds = DEFAULT_SCAN_SECONDS

    scans = 0
    """How many scans this server has run, counting across restarts.

    A real TomoScan keeps its scan number in an autosaved record, so a
    file name is not reused when the IOC comes back. This counted from
    zero in memory instead, and the difference stopped being cosmetic
    the moment a conductor began filing datasets: the same path filed
    twice reaches the keeper under one idempotency key, the second
    registration returns the first record's id without writing an
    event, and that run reads as having produced data nobody recorded.
    A conductor sees a successful call and says nothing.

    So it is loaded from `counter_path` at startup by `load_scans` and
    written after each scan by `_remember_scans`.
    """

    counter_path: Path | None = None
    """Where the count is kept, or `None` to count in memory only.

    `None` is for the tests, which run several servers in one session
    and would otherwise share one file. A deployment always sets it.
    """

    driving = False
    """True while this group is writing the start record itself.

    The putter runs for every write including this group's own, so
    without the guard a scan would start a scan.
    """

    @StartScan.putter
    async def StartScan(self, instance: Any, value: Any) -> str:  # noqa: N802
        """Run a scan, and hold this write open until it has finished.

        Holding it is the busy record's behaviour, and an adapter that
        waits to see the start edge cannot see one against a server that
        behaves this way: by the time the write is answered, the scan is
        over. That was a real defect in the engine adapter, found by
        making the test double behave like this, so the server used for
        commissioning behaves like it too.
        """
        if self.driving:
            return str(value)
        if str(value) in (IDLE, "0", "0.0"):
            return IDLE
        self.scans += 1
        self._remember_scans()
        finished = asyncio.Event()
        asyncio.create_task(self._scan(finished))  # noqa: RUF006
        await finished.wait()
        return IDLE

    def _remember_scans(self) -> None:
        """Write the count down, before the scan rather than after it.

        Before, so a server killed mid-scan still comes back past the
        file name it was about to use. Counting a scan that never
        finished costs a gap in the numbering and nothing else; reusing
        a name costs the silent collision this counter exists to stop.

        A write that fails is ignored. A simulator that refused to scan
        because it could not touch a counter file would be a worse
        instrument than one that repeats a name.
        """
        if self.counter_path is None:
            return
        try:
            self.counter_path.write_text(f"{self.scans}\n", encoding="utf-8")
        except OSError:
            return

    async def _scan(self, finished: asyncio.Event) -> None:
        scan = self.scans
        try:
            await asyncio.sleep(SETTLE_SECONDS)
            self.driving = True
            try:
                await self.StartScan.write(BUSY)
                await self.ScanStatus.write("Scanning")

                # After the busy edge rather than before it, which is
                # where TomoScan mints it: the put follows the base
                # class's own begin_scan. Anything that took the edge as
                # the start of a new run and read this in the same breath
                # would read the previous run's.
                await asyncio.sleep(SETTLE_SECONDS)
                await self.ScanUUID.write(str(uuid.uuid4()))

                await asyncio.sleep(self.scan_seconds)
                await self.ScanStatus.write("Scan complete")
                await self.StartScan.write(IDLE)
            finally:
                self.driving = False

            # The twin of the gap above, on the other edge. TomoScan
            # writes the file name inside end_scan, after the record
            # saying the scan stopped, so a watcher that reads the name
            # the moment it sees idle reads the file the last scan wrote.
            # This server had it on the near side of the edge and so
            # answered correctly a question asked too early, which is a
            # simulator that stays green where a beamline would not.
            #
            # The held write is still answered after this, so a driver
            # waiting on its own put sees the right name and only a
            # watcher of the records can lose the race. That asymmetry is
            # TomoScan's too.
            await asyncio.sleep(SETTLE_SECONDS)
            await self.FullFileName.write(
                f"/local1/{station_of(self.prefix)}/cora-simulated-proposal/scan_{scan:03d}.h5"
            )

            # Answer the held write after the idle value has had a moment
            # to reach whoever is watching, rather than in the same
            # breath. The two are separate deliveries with no ordering
            # between them, and this is the order that catches an adapter
            # reading a monitor cache instead of the server.
            await asyncio.sleep(SETTLE_SECONDS)
        finally:
            finished.set()


def load_scans(counter_path: Path | None) -> int:
    """How many scans have run, as the file left it.

    Zero when there is no file, which is a server that has never run
    one. Zero as well when the file cannot be read as a number, because
    the alternative is refusing to start over a counter: a simulator
    that will not serve is worse than one that repeats a file name, and
    the next scan rewrites the file correctly either way.
    """
    if counter_path is None or not counter_path.exists():
        return 0
    try:
        return int(counter_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tomoscan_sim",
        description="Serve TomoScan-shaped records that scan nothing.",
    )
    parser.add_argument(
        "--prefix",
        required=True,
        help="record prefix, for example corasim2bmb:TomoScan:",
    )
    parser.add_argument(
        "--scan-seconds",
        type=float,
        default=DEFAULT_SCAN_SECONDS,
        help="how long a simulated scan takes",
    )
    parser.add_argument(
        "--counter",
        type=Path,
        default=None,
        help="file holding the scan number, so a restart does not reuse a file name",
    )
    arguments = parser.parse_args(argv)

    ioc = TomoscanSim(prefix=arguments.prefix)
    ioc.scan_seconds = arguments.scan_seconds
    ioc.counter_path = arguments.counter
    ioc.scans = load_scans(arguments.counter)
    run(ioc.pvdb, log_pv_names=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
