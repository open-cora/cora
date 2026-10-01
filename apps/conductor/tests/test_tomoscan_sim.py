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
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import epics
import pytest

from conductor.adapters.tomoscan_engine import TomoscanEngine
from conductor.seams import Citation
from tests.conftest import COUNTER_SERVER_PORT, SIM_SERVER_PORT

if TYPE_CHECKING:
    from types import ModuleType

SIM = Path(__file__).resolve().parents[1] / "infra" / "sim" / "tomoscan_sim.py"
DOUBLE = Path(__file__).resolve().parent / "_tomoscan_ioc.py"


def _sim_module() -> ModuleType:
    """The simulator, imported from the path the service runs it by.

    It ships beside the package rather than inside it, because it is a
    deployment artefact and nothing importable depends on it. The
    checks above read it as text; the ones about the scan counter need
    to call it, and this is the same file either way.
    """
    spec = importlib.util.spec_from_file_location("tomoscan_sim_under_test", SIM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
def test_a_scan_files_a_path_naming_the_station_so_two_beamlines_differ() -> None:
    """The address is how the record tells one run's data from another's.

    This simulator ran at a second beamline and wrote the same literal
    path the first one had, so two executions filed byte-identical
    provenance and only differing principals kept them as two rows.
    """
    engine = TomoscanEngine(
        prefix=PREFIX,
        routines=frozenset({"tomography"}),
        poll_interval=0.05,
        start_timeout=10.0,
        scan_timeout=30.0,
    )

    ran = engine.run("tomography", {"NumAngles": 4}, CITATION)

    assert ran.engine_reference is not None
    assert f"/{PREFIX.split(':', 1)[0]}/" in ran.engine_reference


@pytest.mark.channel_access
@pytest.mark.usefixtures("sim_ioc")
def test_the_sims_text_records_are_char_waveforms_and_not_native_strings() -> None:
    """The type they are served as, which is not the type they were declared as.

    A native EPICS string holds forty characters and a beamline file
    path does not fit in one, which is why TomoScan serves these as
    character waveforms: 2bmb:TomoScan:FullFileName reads back as
    time_char with a count of 256.

    caproto's `report_as_string` turns a declared char array into a
    native string on the wire, so both doubles and this sim served
    time_char nothing and time_string everything, capped at forty. It
    went unseen because every simulated path was shorter than forty
    characters, so nothing was ever cut. The paths are longer now and
    this pins the type, because the length alone would pass again the
    moment somebody shortened one.
    """
    pv = epics.PV(f"{PREFIX}FullFileName")
    assert pv.wait_for_connection(timeout=10)

    assert pv.type == "time_char", f"served as {pv.type}, which caps at forty characters"
    assert pv.count > 40


@pytest.mark.channel_access
@pytest.mark.usefixtures("sim_ioc")
def test_a_scan_file_longer_than_a_native_string_survives_being_read() -> None:
    """Forty characters is where the old shape silently cut a path.

    Read through the engine rather than directly, because the engine is
    what a conductor uses and the question is whether a file name
    reaches a report intact.
    """
    engine = TomoscanEngine(
        prefix=PREFIX,
        routines=frozenset({"tomography"}),
        poll_interval=0.05,
        start_timeout=10.0,
        scan_timeout=30.0,
    )

    ran = engine.run("tomography", {}, CITATION)

    assert ran.engine_reference is not None
    assert len(ran.engine_reference) > 40, (
        f"the simulated path is {len(ran.engine_reference)} characters, which is short "
        "enough that a native string would carry it and the cut would not show"
    )
    assert ran.engine_reference.endswith(".h5")


@pytest.mark.channel_access
@pytest.mark.usefixtures("sim_ioc")
def test_the_sim_says_on_the_network_that_it_is_one() -> None:
    """Whoever finds it while debugging should not have to ask."""
    said = epics.caget(f"{PREFIX}Simulated", as_string=True)
    assert said is not None
    assert "scans nothing" in said


@pytest.mark.channel_access
def test_a_scan_number_survives_a_restart_so_no_file_name_is_reused(tmp_path: Path) -> None:
    """A real TomoScan autosaves this. Counting from zero again is a defect.

    Driven through two servers rather than by calling the counter's
    own methods. Calling them would prove the file is written and not
    that running a scan writes it, which is the half that was missing:
    the first version of this test passed with the call site deleted.

    Not cosmetic, and it was measured rather than reasoned about. A
    conductor files the path its engine returns, keyed for idempotency
    on the step and that path. Two runs under one path reach the keeper
    under one key when the step is not in it, so the second
    registration returns the first record's id, writes no event, and
    leaves that run reading as one whose data nobody recorded while the
    conductor logs a success. The step in the key fixed that half; this
    stops the simulator manufacturing the collision at all.
    """
    counter = tmp_path / "scans"
    prefix = "conductor-tomoscan-counter-test:"

    first = _scan_under_a_fresh_server(prefix, counter)
    second = _scan_under_a_fresh_server(prefix, counter)

    assert first != second, (
        f"both runs of the simulator wrote {first}, so a conductor filing them "
        "would send one idempotency key for two runs"
    )
    assert counter.read_text(encoding="utf-8").strip() == "2"


def _scan_under_a_fresh_server(prefix: str, counter: Path) -> str:
    """Start a simulator, run one scan, stop it, and say what it named.

    A whole server per scan, because a restart is what the test is
    about: the counter lived in the process and came back at zero.
    """
    server = subprocess.Popen(
        [
            sys.executable,
            str(SIM),
            "--prefix",
            prefix,
            "--scan-seconds",
            "0.3",
            "--counter",
            str(counter),
        ],
        env={
            **os.environ,
            "EPICS_CA_ADDR_LIST": f"127.0.0.1:{COUNTER_SERVER_PORT}",
            "EPICS_CA_AUTO_ADDR_LIST": "NO",
            "EPICS_CAS_BEACON_ADDR_LIST": "127.0.0.1",
            "EPICS_CAS_AUTO_BEACON_ADDR_LIST": "NO",
            "EPICS_CA_SERVER_PORT": str(COUNTER_SERVER_PORT),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        running = epics.PV(f"{prefix}ServerRunning")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"the sim exited with {server.returncode} before serving")
            if running.wait_for_connection(timeout=0.2):
                break
        else:
            raise RuntimeError(f"the sim never answered for {prefix}ServerRunning")
        return _one_scan(prefix)
    finally:
        server.terminate()
        server.wait(timeout=10)


def _one_scan(prefix: str) -> str:
    """Run one scan through the engine, and return the file it named."""
    engine = TomoscanEngine(
        prefix=prefix,
        routines=frozenset({"tomography"}),
        poll_interval=0.05,
        start_timeout=10.0,
        scan_timeout=30.0,
    )
    ran = engine.run("tomography", {"NumAngles": 90}, CITATION)
    assert ran.engine_reference is not None
    return ran.engine_reference


def test_a_server_with_no_counter_file_starts_from_zero(tmp_path: Path) -> None:
    """A server that has never run a scan, which is every fresh install."""
    module = _sim_module()
    assert module.load_scans(tmp_path / "absent") == 0
    assert module.load_scans(None) == 0


def test_a_counter_file_of_nonsense_starts_from_zero_rather_than_refusing(
    tmp_path: Path,
) -> None:
    """A simulator that will not serve is worse than one that repeats a name.

    The next scan rewrites the file correctly either way, so the cost
    of reading it is one repeated number and the cost of refusing is a
    commissioning session nobody can run.
    """
    counter = tmp_path / "scans"
    counter.write_text("not a number\n", encoding="utf-8")

    assert _sim_module().load_scans(counter) == 0
