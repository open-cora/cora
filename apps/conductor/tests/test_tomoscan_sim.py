"""The simulated server a conductor is commissioned against.

Two things are worth checking about it and they are different in kind.

That it serves what the adapter reaches for is structural, and reading
the two files answers it without starting anything. That it behaves like
a server is not, so the engine is pointed at it and asked to run a scan.

## Why it is checked against the double as well as against the adapter

`infra/sim/tomoscan_sim.py` and `tests/_tomoscan_ioc.py` are two servers
of the same shape kept apart on purpose: the double carries switches for
provoking failures, the sim carries none because a server that can be
told to misbehave is one somebody will accidentally tell to misbehave.

Two files of the same shape drift. The double is what every engine test
runs against, so a record added there and forgotten here would leave the
adapter proven against something no beamline will ever run.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import epics
import pytest

from conductor.adapters.tomoscan_engine import TomoscanEngine
from conductor.seams import Citation
from tests.conftest import SIM_SERVER_PORT

SIM = Path(__file__).resolve().parents[1] / "infra" / "sim" / "tomoscan_sim.py"
DOUBLE = Path(__file__).resolve().parent / "_tomoscan_ioc.py"

PREFIX = "conductor-tomoscan-sim-test:"

SERVER_PORT = SIM_SERVER_PORT
"""Its own port, so this IOC and the double can serve at once.

Taken from `conftest`, which is where the client's address list is
built, so the two cannot disagree.
"""
SWITCHES = frozenset({"RefuseToStart", "DropCitation", "ReturnAtOnce"})
"""Records the double has for provoking failures, which the sim must not.

Checked rather than assumed. A switch that reached the sim would be a
way to make a beamline's commissioning server lie, reachable by anyone
who can write a record.
"""

MARKERS = frozenset({"Simulated"})
"""Records the sim has and the double does not, saying what it is."""

EXPECTED_RECORDS = 10
"""How many records the sim serves, switches and markers aside.

Pinned because every comparison below is between two sets read off
disk, and two empty sets agree.
"""

CITATION = Citation(
    execution_id="01a0f013-ce25-7670-8ffb-217d13a9318b",
    step_id="01a0f013-ce25-7670-8ffb-218fa11f5741",
)


def _records(path: Path) -> set[str]:
    """Every record a PVGroup in this file declares.

    Class attributes assigned from a call, which is what `pvproperty`
    and the helper wrapping it both are. Read rather than imported so
    this says nothing about which of the two files is importable from
    where.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            match statement:
                case ast.Assign(targets=[ast.Name(id=name)], value=ast.Call()):
                    found.add(name)
                case ast.AnnAssign(target=ast.Name(id=name), value=ast.Call()):
                    found.add(name)
                case _:
                    continue
    return found


def test_the_sim_serves_the_records_the_double_does() -> None:
    """Held to the same shape, so the adapter is proven against what will run."""
    sim = _records(SIM) - MARKERS
    double = _records(DOUBLE) - SWITCHES

    assert len(sim) == EXPECTED_RECORDS, f"the sim serves {sorted(sim)}"
    assert sim == double, (
        f"the sim serves {sorted(sim)} and the double serves {sorted(double)}. "
        "Every engine test runs against the double, so a record only it has is "
        "a record the adapter is proven against and no beamline will run."
    )


def test_the_sim_carries_none_of_the_doubles_switches() -> None:
    """A commissioning server that can be told to misbehave is one that will be."""
    reached = sorted(_records(SIM) & SWITCHES)
    assert not reached, f"the sim declares {reached}, which exist to make a server lie."


@pytest.fixture(scope="module")
def sim_ioc() -> object:
    """Serve the sim on a port of its own, and stop it afterwards."""
    server = subprocess.Popen(
        [sys.executable, str(SIM), "--prefix", PREFIX, "--scan-seconds", "0.6"],
        env={
            **os.environ,
            "EPICS_CA_ADDR_LIST": f"127.0.0.1:{SERVER_PORT}",
            "EPICS_CA_AUTO_ADDR_LIST": "NO",
            "EPICS_CAS_BEACON_ADDR_LIST": "127.0.0.1",
            "EPICS_CAS_AUTO_BEACON_ADDR_LIST": "NO",
            "EPICS_CA_SERVER_PORT": str(SERVER_PORT),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        running = epics.PV(f"{PREFIX}ServerRunning")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"the sim exited with {server.returncode} before serving")
            if running.wait_for_connection(timeout=0.2):
                break
        else:
            raise RuntimeError(f"the sim never answered for {PREFIX}ServerRunning")
        yield None
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.mark.channel_access
@pytest.mark.usefixtures("sim_ioc")
def test_the_engine_runs_a_scan_against_the_sim_and_reads_the_citation_back() -> None:
    """The whole point of it: a conductor can be commissioned on this.

    Structural agreement with the double says the names match. Only
    driving it says the server behaves, and behaving is what a beamline
    will depend on when nobody is watching it.
    """
    engine = TomoscanEngine(
        prefix=PREFIX,
        routines=frozenset({"tomography"}),
        poll_interval=0.05,
        start_timeout=10.0,
        scan_timeout=30.0,
    )

    ran = engine.run("tomography", {"NumAngles": 900}, CITATION)

    assert ran.cites == CITATION
    assert ran.said == "Scan complete"
    assert ran.engine_reference is not None
    assert ran.engine_reference.endswith(".h5")
    assert epics.caget(f"{PREFIX}NumAngles") == 900
    assert epics.caget(f"{PREFIX}StartScan", as_string=True) == "Done"


@pytest.mark.channel_access
@pytest.mark.usefixtures("sim_ioc")
def test_the_sim_says_on_the_network_that_it_is_one() -> None:
    """Whoever finds it while debugging should not have to ask."""
    said = epics.caget(f"{PREFIX}Simulated", as_string=True)
    assert said is not None
    assert "scans nothing" in said
