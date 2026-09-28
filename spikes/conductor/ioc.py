"""A soft IOC serving three motor records over real Channel Access.

No hardware and no EPICS installation: caproto serves Channel Access from
Python, and ophyd connects to it the same way it connects to a real IOC.

This file is thin on purpose. The simulator is `FakeMotorIOC`, caproto's
own, imported rather than reimplemented, because a motor written here
would be a guess about what a motor does and the question this spike asks
is what happens when two clients write to one. An imitation motor that
was lenient about a second writer would answer that question by
construction.

What caproto's simulator gives that matters here: motion takes time at a
velocity, `.STOP` interrupts it, `.SPMG` set to Stop holds it, and
`.DMOV` and `.MOVN` report whether it is moving. Those four are the
fields a rival writer would reach for, and they are the fields ophyd
watches to decide a move is finished.

Three motors rather than one. `mtr1` is the device under test and `mtr2`
is the control: a write to it during a scan is the same act aimed at a
device the scan does not own, which is how the collision scenarios tell
device contention apart from mere concurrency.
"""

from __future__ import annotations

import os

PREFIX = "sim:"
"""Stands in for a beamline's device prefix. Any prefix would do."""

SCANNED = f"{PREFIX}mtr1"
"""The motor the scan moves. Velocity 1.0, limits 0 to 10."""

UNSCANNED = f"{PREFIX}mtr2"
"""The motor nothing scans, so a write to it should disturb nothing."""


def localhost_only() -> None:
    """Keep Channel Access on the loopback.

    Without this, caproto and ophyd search the local network, which is
    slow on a laptop and rude on a facility network. Set before anything
    imports a CA library, because both read the environment at import.
    """
    os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")
    os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")
    # The server half of the same thing. Without it the IOC announces
    # itself to the broadcast address, which is rude on a facility
    # network and which a laptop refuses anyway.
    os.environ.setdefault("EPICS_CAS_BEACON_ADDR_LIST", "127.0.0.1")
    os.environ.setdefault("EPICS_CAS_AUTO_BEACON_ADDR_LIST", "NO")


def serve() -> None:
    """Run the IOC. Intended as a `multiprocessing.Process` target.

    Tracebacks from `broadcast_beacon_loop` are expected and harmless.
    The IOC announces itself every few seconds, `localhost_only` points
    those announcements at the loopback rather than the broadcast
    address, and nothing here runs a Channel Access repeater to receive
    them, so each one fails with a connection refused. Redirecting them
    makes them fewer and quieter, not absent. Nothing measured here
    depends on a beacon reaching anything.
    """
    localhost_only()

    from caproto.ioc_examples.fake_motor_record import FakeMotorIOC
    from caproto.server import run

    ioc = FakeMotorIOC(prefix=PREFIX)
    run(ioc.pvdb, log_pv_names=False)
