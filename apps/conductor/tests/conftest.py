"""One soft IOC for the whole session, and a motor returned home between tests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests import _ioc

if TYPE_CHECKING:
    from collections.abc import Iterator

_ioc.localhost_only()

STARTUP_SECONDS = 3.0
"""How long the IOC is given before anything tries to connect to it."""


@pytest.fixture(scope="session", autouse=True)
def soft_ioc() -> Iterator[None]:
    """Serve the motor records for as long as the session runs."""
    server = _ioc.start()
    time.sleep(STARTUP_SECONDS)
    if server.poll() is not None:
        raise RuntimeError(f"the soft IOC exited at once with {server.returncode}")
    yield
    server.terminate()
    server.wait(timeout=10)


@pytest.fixture
def motor_at_home() -> Iterator[None]:
    """Put the motor back before and after a test that talks to the IOC.

    The unlatching is not tidiness, it is the `rival_hold` finding
    applied to this suite. `.SPMG` is sticky, so one test that holds the
    motor breaks every test after it, which is exactly what happened
    before this existed: three tests failed against a held motor they
    never touched. That is the failure mode the adapter under test exists
    to catch, arriving here first.

    Requested through `usefixtures` in the modules that need it rather
    than autouse, so the core suite, which never opens a socket, does not
    pay two puts and a settle per test.
    """
    import epics

    def unlatch_and_home() -> None:
        epics.caput(f"{_ioc.MOTOR}.SPMG", "Go", wait=True, timeout=10)
        epics.caput(f"{_ioc.OTHER_MOTOR}.SPMG", "Go", wait=True, timeout=10)
        epics.caput(_ioc.MOTOR, 0.0, wait=True, timeout=30)
        time.sleep(0.5)

    unlatch_and_home()
    yield
    unlatch_and_home()
