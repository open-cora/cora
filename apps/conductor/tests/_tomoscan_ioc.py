#!/usr/bin/env python3
"""A soft IOC shaped like TomoScan, for driving the engine adapter against.

Written rather than run, which is the opposite of `_ioc.py` and worth
saying why. That module runs caproto's own motor simulator because a motor
written here would be a guess about what a motor does. There is no
TomoScan simulator to run, so this is a double, and a double is only worth
what it refuses to make easy.

So it imitates the three things the adapter actually depends on and would
otherwise get wrong:

  - starting is not instant. The start record stays idle for a moment
    after it is written, which is what makes the adapter's wait for the
    scan to BEGIN do any work. An IOC that flipped state inside the put
    would let a single wait for completion pass while testing nothing.
  - a scan takes time and then ends, so a wait for completion is a wait.
  - the two citation records hold their last value, like every record.
    That is what makes clearing them observable, and clearing them is the
    behaviour the adapter's docstring argues for at length.

What it does not imitate is anything about tomography. No detector, no
rotation, no file is written. `FullFileName` is set to a plausible string
because the adapter reads it back as the name that joins, and the adapter
neither opens it nor cares what is in it.

Run it as a script rather than with `-m`: `tests/` is on the path pytest
builds and not on a fresh interpreter's, which `_ioc.py` records having
been caught by.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, run

SERVER_PORT = 5094
"""A Channel Access port of this fixture's own.

The motor IOC already owns the default one, and two servers on a host
cannot both answer searches there. Giving this one its own port and
naming both in the client's address list is what lets a session run
them side by side.
"""

CLIENT_ADDR_LIST = f"127.0.0.1:5064 127.0.0.1:{SERVER_PORT}"
"""Both servers, for the client, each with its port written out.

The default port is named rather than left implicit because the two
servers do not share one, so a bare address would reach whichever this
process happens to default to and silently miss the other.
"""

PREFIX = "conductor-tomoscan-test:"
"""Distinct from any real TomoScan prefix, so a test run at a beamline
cannot reach one. The adapter writes a start record, and the difference
between a fixture and a beamline is a tomography scan nobody asked for.
"""

IDLE = "Done"
BUSY = "Scan"
SETTLE_SECONDS = 0.3
"""How long the start record stays idle after being written.

Long enough that an adapter which does not wait for the scan to begin
sees the idle state and wrongly calls the scan finished, which is the
mistake this fixture exists to catch.
"""

SCAN_SECONDS = 0.6


def _text(value: str, size: int = 256) -> Any:
    """A character waveform, which is how TomoScan serves its strings.

    Not cosmetic: a plain EPICS string holds 40 characters, and a file
    path does not fit in one. Reading these without `as_string` gives an
    array of integers, which the adapter is written to avoid.
    """
    return pvproperty(
        value=value,
        dtype=ChannelType.CHAR,
        max_length=size,
        string_encoding="utf-8",
    )


class TomoscanIOC(PVGroup):
    """The records the engine adapter reads and writes, and no others."""

    ServerRunning = pvproperty(value="Running", dtype=ChannelType.STRING)

    # An enum, because TomoScan's is a busy record: a client writes 1 and
    # reads back a word. A plain string channel would accept the write and
    # then let the adapter compare against something no real server sends.
    StartScan: Any = pvproperty(value=IDLE, enum_strings=[IDLE, BUSY], dtype=ChannelType.ENUM)
    ScanStatus = _text("Scan complete")
    FullFileName = _text("")
    KeeperExecutionId = _text("")
    KeeperStepId = _text("")

    CameraPVPrefix = pvproperty(value="tomoscan-test-cam:", dtype=ChannelType.STRING)
    FilePluginPVPrefix = pvproperty(value="tomoscan-test-cam:HDF1:", dtype=ChannelType.STRING)
    """Where the camera and the file plugin are, which the engine reads back.

    `stringout` upstream rather than the character waveforms beside them,
    so the shape is copied from the template and not from the neighbours.

    Served because the engine adapter refuses a server holding either one
    blank: that is what a TomoScan looks like when it started before the
    server holding its optics configuration, and it is the state in which
    a scan runs and writes no file. A stand-in that did not serve them
    would make that refusal untestable here and would fire it at every
    beamline running one of these.

    What cannot be reproduced here is the emptier half of that state. A
    record TomoScan never filled in holds the empty string, and a
    caproto string channel will not take one from a client or from the
    server: both writes are zero elements, which it accepts and ignores.
    A space is as blank as this fixture goes, and the adapter strips
    before judging so that the two cannot differ.
    """

    ScanUUID = pvproperty(value="Unknown", dtype=ChannelType.STRING)
    """What the engine calls one run, in the sim's shape and for its reason."""

    # Three switches with no counterpart in TomoScan, for reproducing the
    # ways a real server disappoints an adapter. Racing a real scan to
    # cause any of them would be a test that passes on a fast machine.
    RefuseToStart = pvproperty(value=0, dtype=ChannelType.LONG)
    DropCitation = pvproperty(value=0, dtype=ChannelType.LONG)

    # 2-BM's StartScan.RTYP reads `busy`, and a busy record holds a
    # client's completion callback until the record returns to zero. So
    # put(wait=True) against the real thing blocks for the whole scan,
    # and this double blocks too. The switch turns that off, because an
    # adapter should not care which it is talking to, and the only way to
    # show that is to run it against both.
    ReturnAtOnce = pvproperty(value=0, dtype=ChannelType.LONG)

    NumAngles = pvproperty(value=1500, dtype=ChannelType.LONG)
    ExposureTime = pvproperty(value=0.1, dtype=ChannelType.DOUBLE)
    RotationStart = pvproperty(value=0.0, dtype=ChannelType.DOUBLE)
    RotationStep = pvproperty(value=0.12, dtype=ChannelType.DOUBLE)

    scans = 0
    """How many scans have been asked for, so a test can count them."""

    driving = False
    """True while this group is writing the start record itself.

    The putter runs for every write including the group's own, so without
    this a scan would start a scan.
    """

    @StartScan.putter
    async def StartScan(self, instance: Any, value: Any) -> str:  # noqa: N802
        """Run a scan, and by default do not answer until it has ended.

        Stays idle for a moment and becomes busy after, which is the
        settling this fixture exists to reproduce.

        Not answering is the busy record's whole behaviour and it is what
        an adapter has to survive. A putter that returned at once would
        let an adapter that waits for the start edge look correct here and
        then fail at a beamline on any scan shorter than the client's put
        timeout, which is the worst shape of bug available: it passes on
        long scans and fails on short ones.
        """
        if self.driving:
            return str(value)
        if str(value) in (IDLE, "0", "0.0"):
            return IDLE
        if self.RefuseToStart.value:
            return IDLE
        self.scans += 1
        finished = asyncio.Event()
        asyncio.create_task(self._scan(finished))  # noqa: RUF006
        if not self.ReturnAtOnce.value:
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
                await asyncio.sleep(SETTLE_SECONDS)
                await self.ScanUUID.write(str(uuid.uuid4()))
                await asyncio.sleep(SCAN_SECONDS)
                if self.DropCitation.value:
                    await self.KeeperExecutionId.write("")
                    await self.KeeperStepId.write("")
                await self.ScanStatus.write("Scan complete")
                await self.StartScan.write(IDLE)
            finally:
                self.driving = False

            # Both late records land on the far side of the edge that
            # announces them, which is where TomoScan puts them and what
            # the sim reproduces. Keeping the two servers the same here
            # matters more than anywhere else: the engine adapter is
            # proven against this one and no beamline will ever run it.
            await asyncio.sleep(SETTLE_SECONDS)
            await self.FullFileName.write(f"/local1/2BM/tomoscan-test-proposal/scan_{scan:03d}.h5")

            # Answer the held write a moment after going idle, rather than
            # in the same breath. A client's monitor for the idle value and
            # its answer to the write are two deliveries with no ordering
            # between them, and the unfavourable one is that the monitor
            # lands first. That is the interleaving a loaded client sees,
            # and racing a real server to produce it would be a test that
            # passes on a fast machine.
            await asyncio.sleep(SETTLE_SECONDS)
        finally:
            finished.set()


def start() -> subprocess.Popen[bytes]:
    """Serve the TomoScan records, and hand back the process serving them.

    By path rather than `-m`, because this file lives under `tests/`,
    which is on the path pytest built and not on a fresh interpreter's.
    """
    script = Path(__file__).resolve()
    return subprocess.Popen(
        [sys.executable, str(script), "--prefix", PREFIX],
        env={**os.environ, **_loopback()},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _loopback() -> dict[str, str]:
    """The four variables that keep client and server off the network."""
    return {
        "EPICS_CA_ADDR_LIST": CLIENT_ADDR_LIST,
        "EPICS_CA_AUTO_ADDR_LIST": "NO",
        "EPICS_CAS_BEACON_ADDR_LIST": "127.0.0.1",
        "EPICS_CAS_AUTO_BEACON_ADDR_LIST": "NO",
        # The server port, and caproto reads this one rather than the
        # EPICS_CAS_ spelling. Setting the other has no effect at all and
        # leaves the second IOC quietly bound to the first one's port.
        "EPICS_CA_SERVER_PORT": str(SERVER_PORT),
    }


def wait_until_serving(server: subprocess.Popen[bytes], timeout: float) -> None:
    """Block until the IOC answers a search, or say why it never did."""
    import epics

    running = epics.PV(f"{PREFIX}ServerRunning")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the TomoScan IOC exited with {server.returncode} before serving")
        if running.wait_for_connection(timeout=0.2):
            return
    raise RuntimeError(
        f"the TomoScan IOC did not answer for {PREFIX}ServerRunning within {timeout:g}s"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    arguments = parser.parse_args()
    ioc = TomoscanIOC(prefix=arguments.prefix)
    run(ioc.pvdb, log_pv_names=False)


if __name__ == "__main__":
    main()
