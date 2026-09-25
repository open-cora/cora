"""A soft IOC the control adapter can be driven against.

caproto's own `FakeMotorIOC`, run rather than reimplemented, for the
reason a spike made the same choice: a motor written here would be a
guess about what a motor does, and a lenient guess would answer the
questions these tests ask by construction. What it gives that matters is
motion that takes time, a `.STOP` that interrupts it, an `.SPMG` that
holds it and a `.RBV` that reports where the motor actually is.

## Why a subprocess rather than a `multiprocessing.Process`

A process started by `multiprocessing` under the spawn method, which is
the default on macOS, re-imports the module holding its target so it can
unpickle it. This module lives under `tests/`, which is on the path
pytest built and not on the one a fresh interpreter starts with, so the
child died on import and every connection timed out against an IOC that
was never serving. Running caproto's own entry point through
`sys.executable` has nothing to pickle and nothing to re-import.

The prefix differs from the spike's on purpose. Both serve Channel
Access, and a test run beside a spike run should not find the spike's
motors.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

PREFIX = "conductor-test:"
"""Distinct from the spike's `sim:`, so the two can never be confused."""

MOTOR = f"{PREFIX}mtr1"
"""The motor the tests move. Velocity 1.0, limits 0 to 10."""

OTHER_MOTOR = f"{PREFIX}mtr2"
"""A second motor, for checking that one record's trouble stays there."""

ABSENT = f"{PREFIX}nothing_serves_this"
"""A name nothing answers to, for the unreachable path."""

ENTRY_POINT = "caproto.ioc_examples.fake_motor_record"
"""caproto's own runnable simulator, taking `--prefix`."""


def localhost_only() -> None:
    """Keep Channel Access on the loopback, before any CA library loads."""
    for name, value in _loopback().items():
        os.environ.setdefault(name, value)


def _loopback() -> dict[str, str]:
    """The four variables that keep client and server off the network."""
    return {
        "EPICS_CA_ADDR_LIST": "127.0.0.1",
        "EPICS_CA_AUTO_ADDR_LIST": "NO",
        "EPICS_CAS_BEACON_ADDR_LIST": "127.0.0.1",
        "EPICS_CAS_AUTO_BEACON_ADDR_LIST": "NO",
    }


def start() -> subprocess.Popen[bytes]:
    """Serve the motor records, and hand back the process serving them.

    Output is discarded. Tracebacks from `broadcast_beacon_loop` are
    expected and harmless: the IOC announces itself, those announcements
    are pointed at the loopback, and nothing here runs a Channel Access
    repeater to receive them.
    """
    return subprocess.Popen(
        [sys.executable, "-m", ENTRY_POINT, "--prefix", PREFIX],
        env={**os.environ, **_loopback()},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_until_serving(server: subprocess.Popen[bytes], timeout: float) -> None:
    """Block until the IOC answers a search, or say why it never did.

    A fixed sleep stood here, and a fixed sleep is the wrong shape for a
    wait on a machine of unknown speed. Too short and every Channel
    Access test fails against an IOC that was only slow to start, with a
    connection timeout for a message and nothing pointing at the real
    cause. Too long and every run on every machine pays for the slowest
    one that ever ran it. This waits for the answer instead, so a quick
    machine pays a fraction of a second and a cold one gets as long as it
    needs.

    The subprocess is polled on the way round because the two failures
    need different messages: an IOC that exited has a return code worth
    printing, and one that is still running but silent does not.

    `epics` is imported here rather than at module scope because
    `localhost_only()` has to set its four variables before the library
    loads, and that call is made by the importing conftest.
    """
    import epics

    readback = epics.PV(f"{MOTOR}.RBV")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the soft IOC exited with {server.returncode} before serving")
        if readback.wait_for_connection(timeout=0.2):
            return
    raise RuntimeError(
        f"the soft IOC did not answer for {MOTOR} within {timeout:g}s, "
        "though its process is still running"
    )
