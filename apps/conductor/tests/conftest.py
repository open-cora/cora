"""One soft IOC for the whole session, and a motor returned home between tests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests import _ioc

if TYPE_CHECKING:
    from collections.abc import Iterator

_ioc.localhost_only()

STARTUP_TIMEOUT = 30.0
"""How long the IOC may take to answer before the session gives up.

Generous, and it costs nothing when it is not needed: the wait below
returns as soon as the IOC answers, so this is the budget for the
slowest machine rather than the price every machine pays.
"""


@pytest.fixture(scope="session", autouse=True)
def soft_ioc() -> Iterator[None]:
    """Serve the motor records for as long as the session runs."""
    server = _ioc.start()
    try:
        _ioc.wait_until_serving(server, STARTUP_TIMEOUT)
    except BaseException:
        # A started IOC outlives a failed wait otherwise, and the next run
        # finds the port taken by a process nothing is tracking.
        server.terminate()
        server.wait(timeout=10)
        raise
    yield
    server.terminate()
    server.wait(timeout=10)


HOMING_SETTLE = 20.0
"""Longer than the adapter's default, because a motor may be homing the full travel."""


@pytest.fixture
def motor_at_home() -> Iterator[None]:
    """Both motors unlatched and at zero before a test talks to the IOC.

    The unlatching is not tidiness, it is the `rival_hold` finding
    applied to this suite. `.SPMG` is sticky, so one test that holds a
    motor breaks every test after it, which is exactly what happened
    before this existed: three tests failed against a held motor they
    never touched. That is the failure mode the adapter under test exists
    to catch, arriving here first.

    ## Why this homes through the adapter rather than through a put

    It used to be `epics.caput(..., wait=True)` followed by half a
    second, and that is not a home. A put returns while the motor is
    still travelling, which this suite already knows: it is the whole
    documented lesson of
    `test_move_on_a_held_motor_leaves_it_where_it_was`, which failed at
    0.5556 until it was rewritten to place the motor through the adapter.
    The fixture was still doing the thing that test was fixed to stop
    doing.

    What it cost was not a slow test but a false one.
    `test_move_a_rival_redirects_mid_flight_does_not_claim_arrival`
    passed in a full run and failed eight times out of eight on its own,
    because in a full run it inherited a motor still travelling back from
    the previous test and that residual motion, rather than the adapter,
    was what made its assertion hold.

    So the fixture uses `EpicsControl`, which waits on the readback and
    on `.DMOV`. That it is the class under test is not circular in a way
    that hides anything: a broken `move` makes these tests fail loudly
    rather than quietly pass, which is the opposite of what the put did.

    Both motors are homed, not just the first, because a test that reads
    a position it did not set is the defect above in another costume. The
    deadband is put back for the same reason: it is sticky like `.SPMG`,
    it widens the window a move is accepted in, and a test that leaves it
    raised would loosen every test after it.

    Requested through `usefixtures` in the modules that need it rather
    than autouse, so the core suite, which never opens a socket, does not
    pay for a beamline it does not use.
    """
    import epics

    from conductor.adapters.epics_control import DEADBAND_FIELD, EpicsControl

    for motor in (_ioc.MOTOR, _ioc.OTHER_MOTOR):
        epics.caput(f"{motor}.SPMG", "Go", wait=True, timeout=10)
        epics.caput(f"{motor}.{DEADBAND_FIELD}", 0.0, wait=True, timeout=10)
    time.sleep(0.2)
    with EpicsControl(settle=HOMING_SETTLE) as control:
        for motor in (_ioc.MOTOR, _ioc.OTHER_MOTOR):
            control.move(motor, 0.0)
    yield
