"""The TomoScan engine adapter, driven against a soft IOC shaped like one.

`tests/_tomoscan_ioc.py` says what it does and does not imitate. What
matters for reading these is that starting is not instant there, so a
wait for the scan to begin is a wait that can fail.
"""

from __future__ import annotations

from typing import Any

import epics
import pytest

from conductor.adapters.tomoscan_engine import (
    EngineNotRunningError,
    ScanDidNotStartError,
    TomoscanEngine,
    UnknownRoutineError,
    UnreachableEngineError,
)
from conductor.seams import Citation, ReferenceNotCarriedError
from tests import _tomoscan_ioc

pytestmark = [pytest.mark.channel_access, pytest.mark.usefixtures("tomoscan_ioc")]

ROUTINE = "tomography"
CITATION = Citation(
    execution_id="01a0f013-ce25-7670-8ffb-217d13a9318b",
    step_id="01a0f013-ce25-7670-8ffb-218fa11f5741",
)


def engine(**overrides: object) -> TomoscanEngine:
    settings: dict[str, object] = {
        "prefix": _tomoscan_ioc.PREFIX,
        "routines": frozenset({ROUTINE}),
        "poll_interval": 0.05,
        "start_timeout": 10.0,
        "scan_timeout": 30.0,
    }
    settings.update(overrides)
    return TomoscanEngine(**settings)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def engine_ready() -> None:
    """Undo whatever the last test set, so each starts from a served scan."""
    for suffix, value in (
        ("ServerRunning", "Running"),
        ("RefuseToStart", 0),
        ("DropCitation", 0),
        ("ReturnAtOnce", 0),
        ("KeeperExecutionId", ""),
        ("KeeperStepId", ""),
    ):
        epics.caput(f"{_tomoscan_ioc.PREFIX}{suffix}", value, wait=True, timeout=10)


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
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}NumAngles") == 900
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}ExposureTime") == pytest.approx(0.25)


def test_a_routine_this_engine_was_not_given_is_refused() -> None:
    with pytest.raises(UnknownRoutineError) as refused:
        engine().run("something-else", {}, CITATION)
    assert refused.value.routine == "something-else"


def test_a_routine_this_engine_was_not_given_writes_no_parameters() -> None:
    before = epics.caget(f"{_tomoscan_ioc.PREFIX}NumAngles")
    with pytest.raises(UnknownRoutineError):
        engine().run("something-else", {"NumAngles": 4242}, CITATION)
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}NumAngles") == before


def test_a_server_that_is_not_running_is_refused() -> None:
    epics.caput(f"{_tomoscan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)
    with pytest.raises(EngineNotRunningError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.said == "Stopped"


def test_a_server_that_is_not_running_keeps_its_settings() -> None:
    """A refusal that had already written would leave the next scan poisoned."""
    before = epics.caget(f"{_tomoscan_ioc.PREFIX}ExposureTime")
    epics.caput(f"{_tomoscan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)
    with pytest.raises(EngineNotRunningError):
        engine().run(ROUTINE, {"ExposureTime": 9.5}, CITATION)
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}ExposureTime") == pytest.approx(before)


def test_a_server_that_holds_the_write_open_until_the_scan_ends_is_understood() -> None:
    """2-BM's StartScan is a busy record, so this is the real shape.

    A busy record keeps a client's write pending until it returns to
    zero, so the scan is over before the caller regains control and
    there is no start edge left for it to see. An adapter waiting for
    one passed anyway while pyepics answered from a monitor cache
    running fifty milliseconds behind the server, and would have failed
    on any host slow enough to miss that window.
    """
    ran = engine().run(ROUTINE, {}, CITATION)
    assert ran.said == "Scan complete"
    assert ran.cites == CITATION
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}StartScan", as_string=True) == "Done"


def test_a_server_that_answers_the_write_before_scanning_is_understood_too() -> None:
    """The other half, and the reason the first is not simply the rule.

    Nothing in Channel Access says which of the two a server is, and an
    adapter that assumed either one would be wrong at some beamline. So
    both are driven here rather than the one this station happens to
    have.
    """
    epics.caput(f"{_tomoscan_ioc.PREFIX}ReturnAtOnce", 1, wait=True, timeout=10)
    ran = engine().run(ROUTINE, {}, CITATION)
    assert ran.said == "Scan complete"
    assert ran.cites == CITATION


def test_a_scan_that_never_starts_is_refused_rather_than_called_finished() -> None:
    epics.caput(f"{_tomoscan_ioc.PREFIX}RefuseToStart", 1, wait=True, timeout=10)
    with pytest.raises(ScanDidNotStartError) as refused:
        engine(start_timeout=1.0).run(ROUTINE, {}, CITATION)
    assert refused.value.routine == ROUTINE


def test_an_engine_that_dropped_the_ids_is_refused_rather_than_reported_done() -> None:
    epics.caput(f"{_tomoscan_ioc.PREFIX}DropCitation", 1, wait=True, timeout=10)
    with pytest.raises(ReferenceNotCarriedError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.asked == CITATION
    assert refused.value.got is None


def test_a_prefix_nothing_answers_to_is_refused() -> None:
    driver = engine(prefix="conductor-tomoscan-absent:", connect_timeout=0.5)
    with pytest.raises(UnreachableEngineError):
        driver.run(ROUTINE, {}, CITATION)


def test_a_prefix_nothing_answers_to_says_no_scan_was_started() -> None:
    driver = engine(prefix="conductor-tomoscan-absent:", connect_timeout=0.5)
    with pytest.raises(UnreachableEngineError) as refused:
        driver.run(ROUTINE, {}, CITATION)
    assert refused.value.started is False
    assert "no scan was started" in str(refused.value)


class _AnswersOnceThenStops(epics.PV):
    """A channel that connects for the read before the start and none after.

    Standing in for a server that disappears while a scan is running,
    which is what happened at a beamline: the status record was read
    once to record what the engine had produced before being asked, and
    the engine was gone by the time it was read again.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._answered = False

    def wait_for_connection(self, timeout: float | None = None) -> bool:
        if self._answered:
            return False
        self._answered = True
        return bool(super().wait_for_connection(timeout=timeout))


def test_an_engine_lost_after_the_start_does_not_claim_no_scan_was_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two readings want opposite responses from whoever reads the record.

    A scan that never began needs nobody to go and look. One that began
    and went out of sight may still be driving something.
    """
    status = f"{_tomoscan_ioc.PREFIX}ScanStatus"
    real = epics.PV

    def build(name: str, **kwargs: Any) -> epics.PV:
        if name == status:
            return _AnswersOnceThenStops(name, **kwargs)
        return real(name, **kwargs)

    monkeypatch.setattr(epics, "PV", build)

    with pytest.raises(UnreachableEngineError) as refused:
        engine(connect_timeout=0.5).run(ROUTINE, {}, CITATION)

    assert refused.value.started is True
    assert "after the scan had been started" in str(refused.value)
    assert "no scan was started" not in str(refused.value)
