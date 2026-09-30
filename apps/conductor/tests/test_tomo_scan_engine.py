"""The TomoScan engine adapter, driven against a soft IOC shaped like one.

`tests/_tomo_scan_ioc.py` says what it does and does not imitate. What
matters for reading these is that starting is not instant there, so a
wait for the scan to begin is a wait that can fail.
"""

from __future__ import annotations

import epics
import pytest

from conductor.adapters.tomo_scan_engine import (
    EngineNotRunningError,
    ScanDidNotStartError,
    TomoScanEngine,
    UnknownRoutineError,
    UnreachableEngineError,
)
from conductor.seams import Citation, ReferenceNotCarriedError
from tests import _tomo_scan_ioc

pytestmark = [pytest.mark.channel_access, pytest.mark.usefixtures("tomoscan_ioc")]

ROUTINE = "tomography"
CITATION = Citation(
    execution_id="01a0f013-ce25-7670-8ffb-217d13a9318b",
    step_id="01a0f013-ce25-7670-8ffb-218fa11f5741",
)


def engine(**overrides: object) -> TomoScanEngine:
    settings: dict[str, object] = {
        "prefix": _tomo_scan_ioc.PREFIX,
        "routines": frozenset({ROUTINE}),
        "poll_interval": 0.05,
        "start_timeout": 10.0,
        "scan_timeout": 30.0,
    }
    settings.update(overrides)
    return TomoScanEngine(**settings)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def engine_ready() -> None:
    """Undo whatever the last test set, so each starts from a served scan."""
    for suffix, value in (
        ("ServerRunning", "Running"),
        ("RefuseToStart", 0),
        ("DropCitation", 0),
        ("KeeperExecutionId", ""),
        ("KeeperStepId", ""),
    ):
        epics.caput(f"{_tomo_scan_ioc.PREFIX}{suffix}", value, wait=True, timeout=10)


def test_a_finished_scan_returns_the_file_the_engine_recorded() -> None:
    ran = engine().run(ROUTINE, {}, CITATION)
    assert ran.engine_reference is not None
    assert ran.engine_reference.endswith(".h5")


def test_a_finished_scan_says_what_the_engine_said_about_it() -> None:
    ran = engine().run(ROUTINE, {}, CITATION)
    assert ran.said == "Scan complete"


def test_a_finished_scan_reads_the_citation_back_out_of_the_records() -> None:
    ran = engine().run(ROUTINE, {}, CITATION)
    assert ran.cites == CITATION


def test_a_scan_with_no_citation_clears_what_the_last_scan_left() -> None:
    """The reason the adapter writes empties rather than writing nothing.

    A record keeps its last value, so a scan run with no citation after
    one that had ids would otherwise read those ids back and claim a step
    it had nothing to do with.
    """
    driver = engine()
    driver.run(ROUTINE, {}, CITATION)
    assert driver.run(ROUTINE, {}, None).cites is None


def test_parameters_reach_the_records_they_name() -> None:
    engine().run(ROUTINE, {"NumAngles": 900, "ExposureTime": 0.25}, CITATION)
    assert epics.caget(f"{_tomo_scan_ioc.PREFIX}NumAngles") == 900
    assert epics.caget(f"{_tomo_scan_ioc.PREFIX}ExposureTime") == pytest.approx(0.25)


def test_a_routine_this_engine_was_not_given_is_refused() -> None:
    with pytest.raises(UnknownRoutineError) as refused:
        engine().run("something-else", {}, CITATION)
    assert refused.value.routine == "something-else"


def test_a_routine_this_engine_was_not_given_writes_no_parameters() -> None:
    before = epics.caget(f"{_tomo_scan_ioc.PREFIX}NumAngles")
    with pytest.raises(UnknownRoutineError):
        engine().run("something-else", {"NumAngles": 4242}, CITATION)
    assert epics.caget(f"{_tomo_scan_ioc.PREFIX}NumAngles") == before


def test_a_server_that_is_not_running_is_refused() -> None:
    epics.caput(f"{_tomo_scan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)
    with pytest.raises(EngineNotRunningError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.said == "Stopped"


def test_a_server_that_is_not_running_keeps_its_settings() -> None:
    """A refusal that had already written would leave the next scan poisoned."""
    before = epics.caget(f"{_tomo_scan_ioc.PREFIX}ExposureTime")
    epics.caput(f"{_tomo_scan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)
    with pytest.raises(EngineNotRunningError):
        engine().run(ROUTINE, {"ExposureTime": 9.5}, CITATION)
    assert epics.caget(f"{_tomo_scan_ioc.PREFIX}ExposureTime") == pytest.approx(before)


def test_a_scan_that_never_starts_is_refused_rather_than_called_finished() -> None:
    epics.caput(f"{_tomo_scan_ioc.PREFIX}RefuseToStart", 1, wait=True, timeout=10)
    with pytest.raises(ScanDidNotStartError) as refused:
        engine(start_timeout=1.0).run(ROUTINE, {}, CITATION)
    assert refused.value.routine == ROUTINE


def test_an_engine_that_dropped_the_ids_is_refused_rather_than_reported_done() -> None:
    epics.caput(f"{_tomo_scan_ioc.PREFIX}DropCitation", 1, wait=True, timeout=10)
    with pytest.raises(ReferenceNotCarriedError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.asked == CITATION
    assert refused.value.got is None


def test_a_prefix_nothing_answers_to_is_refused() -> None:
    driver = engine(prefix="conductor-tomoscan-absent:", connect_timeout=0.5)
    with pytest.raises(UnreachableEngineError):
        driver.run(ROUTINE, {}, CITATION)
