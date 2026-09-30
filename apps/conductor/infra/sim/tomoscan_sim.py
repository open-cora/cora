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
held to the same record names by
`tests/test_the_sim_matches_the_double.py`.

Not a simulation of tomography. Nothing here models angles, exposure or
a detector. The parameters exist so that a procedure setting them is
exercised end to end, and they are written down and read back and
otherwise ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
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
        report_as_string=True,
        string_encoding="utf-8",
    )


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
    KeeperExecutionId = _text("")
    KeeperStepId = _text("")

    StartScan: Any = pvproperty(value=IDLE, enum_strings=[IDLE, BUSY], dtype=ChannelType.ENUM)

    NumAngles = pvproperty(value=1500, dtype=ChannelType.LONG)
    ExposureTime = pvproperty(value=0.1, dtype=ChannelType.DOUBLE)
    RotationStart = pvproperty(value=0.0, dtype=ChannelType.DOUBLE)
    RotationStep = pvproperty(value=0.12, dtype=ChannelType.DOUBLE)

    scan_seconds = DEFAULT_SCAN_SECONDS
    scans = 0

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
        finished = asyncio.Event()
        asyncio.create_task(self._scan(finished))  # noqa: RUF006
        await finished.wait()
        return IDLE

    async def _scan(self, finished: asyncio.Event) -> None:
        scan = self.scans
        try:
            await asyncio.sleep(SETTLE_SECONDS)
            self.driving = True
            try:
                await self.StartScan.write(BUSY)
                await self.ScanStatus.write("Scanning")
                await asyncio.sleep(self.scan_seconds)
                await self.FullFileName.write(f"/tmp/cora-sim/scan_{scan:03d}.h5")
                await self.ScanStatus.write("Scan complete")
                await self.StartScan.write(IDLE)
            finally:
                self.driving = False

            # Answer the held write after the idle value has had a moment
            # to reach whoever is watching, rather than in the same
            # breath. The two are separate deliveries with no ordering
            # between them, and this is the order that catches an adapter
            # reading a monitor cache instead of the server.
            await asyncio.sleep(SETTLE_SECONDS)
        finally:
            finished.set()


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
    arguments = parser.parse_args(argv)

    ioc = TomoscanSim(prefix=arguments.prefix)
    ioc.scan_seconds = arguments.scan_seconds
    run(ioc.pvdb, log_pv_names=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
