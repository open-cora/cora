"""The TomoScan engine adapter, driven against a soft IOC shaped like one.

`tests/_tomoscan_ioc.py` says what it does and does not imitate. What
matters for reading these is that starting is not instant there, so a
wait for the scan to begin is a wait that can fail.
"""

from __future__ import annotations

import time
from typing import Any

import epics
import pytest

from conductor.adapters.tomoscan_engine import (
    EngineNotConfiguredError,
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


def wait_until_quiet(settle: float = 0.3, limit: float = 20.0) -> None:
    """Wait out a scan the previous test left running.

    `ReturnAtOnce` answers the start write before the scan is over, so
    that scan outlives the test that began it and goes on writing
    records. The file name is the last thing it writes and it lands
    after the idle edge, which is where TomoScan writes it, so the write
    arrives well after the test that caused it has finished.

    The next test then sees a record move for a reason it did not cause,
    and `_await_started` reads any movement in that pair as a scan
    beginning. The symptom is a scan that was refused looking as though
    it started, in whichever test happens to run next.

    Waiting for idle would not do it, because the file name is written
    after idle. So this waits for the records to stop moving at all.
    """
    watched = ("StartScan", "ScanStatus", "FullFileName")
    deadline = time.monotonic() + limit
    seen: tuple[str, ...] | None = None
    since = time.monotonic()
    while time.monotonic() < deadline:
        now = tuple(
            str(epics.caget(f"{_tomoscan_ioc.PREFIX}{suffix}", as_string=True))
            for suffix in watched
        )
        if now != seen:
            seen, since = now, time.monotonic()
        elif time.monotonic() - since >= settle:
            return
        time.sleep(0.05)


@pytest.fixture(autouse=True)
def engine_ready() -> None:
    """Undo whatever the last test set, so each starts from a served scan."""
    wait_until_quiet()
    for suffix, value in (
        ("ServerRunning", "Running"),
        ("RefuseToStart", 0),
        ("DropCitation", 0),
        ("ReturnAtOnce", 0),
        ("KeeperExecutionId", ""),
        ("KeeperStepId", ""),
        ("CameraPVPrefix", "tomoscan-test-cam:"),
        ("FilePluginPVPrefix", "tomoscan-test-cam:HDF1:"),
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


def blank(*suffixes: str) -> tuple[str, ...]:
    """Blank these prefixes, and prove they are blank before anything reads them.

    The readback is asserted rather than trusted. A write of the empty
    string to one of these is a write of zero elements, which the server
    accepts and ignores, so the obvious way to do this leaves the record
    holding what it had. A test that blanked nothing and then watched
    the engine proceed would look exactly like a missing guard.

    `_tomoscan_ioc` records why a space is as empty as these get.

    Read past the monitor cache, for the reason the adapter's own reads
    are. The fixture above writes these records immediately before this
    runs, and a cached get answered with that write rather than with
    this one, in one of the two records and not the other.
    """
    records = tuple(f"{_tomoscan_ioc.PREFIX}{suffix}" for suffix in suffixes)
    for record in records:
        epics.caput(record, " ", wait=True, timeout=10)
        value = epics.PV(record).get(as_string=True, use_monitor=False)
        read = "" if value is None else str(value)
        assert read.strip() == "", f"{record} reads {read!r}, so this test would prove nothing"
    return records


def test_a_server_that_says_where_to_write_for_neither_names_both_records() -> None:
    records = blank("CameraPVPrefix", "FilePluginPVPrefix")
    with pytest.raises(EngineNotConfiguredError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.records == records


@pytest.mark.parametrize("blanked", ["CameraPVPrefix", "FilePluginPVPrefix"])
def test_a_server_holding_one_blank_prefix_is_refused(blanked: str) -> None:
    """Either one alone, because a scan needs both and one is enough to lose it."""
    records = blank(blanked)
    with pytest.raises(EngineNotConfiguredError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.records == records


def test_a_server_that_does_not_say_where_to_write_keeps_its_settings() -> None:
    """The same reason the stopped-server refusal checks it.

    This one matters more. A stopped server cannot act on what it was
    left holding, and this server is running: somebody pressing start
    from the screen would scan on whatever exposure time a refused
    dispatch had already written.
    """
    before = epics.caget(f"{_tomoscan_ioc.PREFIX}ExposureTime")
    blank("CameraPVPrefix", "FilePluginPVPrefix")
    with pytest.raises(EngineNotConfiguredError):
        engine().run(ROUTINE, {"ExposureTime": 9.5}, CITATION)
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}ExposureTime") == pytest.approx(before)


def test_a_server_that_does_not_say_where_to_write_starts_no_scan() -> None:
    scanned = epics.caget(f"{_tomoscan_ioc.PREFIX}ScanStatus", as_string=True)
    blank("CameraPVPrefix", "FilePluginPVPrefix")
    with pytest.raises(EngineNotConfiguredError):
        engine().run(ROUTINE, {}, CITATION)
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}StartScan", as_string=True) == "Done"
    assert epics.caget(f"{_tomoscan_ioc.PREFIX}ScanStatus", as_string=True) == scanned


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

    One instance stands for the server rather than for a channel to
    it, so that asking again through a new channel meets the same
    silence. An engine that rebuilds an unresolved channel would
    otherwise be handed a fresh one that answers.
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

    absent: list[epics.PV] = []

    def build(name: str, **kwargs: Any) -> epics.PV:
        if name != status:
            return real(name, **kwargs)
        if not absent:
            absent.append(_AnswersOnceThenStops(name, **kwargs))
        return absent[0]

    monkeypatch.setattr(epics, "PV", build)

    with pytest.raises(UnreachableEngineError) as refused:
        engine(connect_timeout=0.5).run(ROUTINE, {}, CITATION)

    assert refused.value.started is True
    assert "after the scan had been started" in str(refused.value)
    assert "no scan was started" not in str(refused.value)


class _StaleAfterAnOutage(epics.PV):
    """A channel that stops resolving once its server has been away.

    Standing in for what was measured at a beamline: a server that is
    back and answers a new search in the same instant, while the
    channel kept across its absence is still waiting out a retry
    interval that widened while it was away.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.stale = False

    def wait_for_connection(self, timeout: float | None = None) -> bool:
        if self.stale:
            return False
        return bool(super().wait_for_connection(timeout=timeout))


def test_an_engine_rebuilds_a_channel_an_outage_left_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Holding the channel would inherit a search interval grown while away.

    The run after an outage is the one that would wait it out, so it
    is the run this drives: the first leaves a channel behind, and the
    second has to reach the server rather than the schedule.
    """
    running = f"{_tomoscan_ioc.PREFIX}ServerRunning"
    real = epics.PV
    built: list[str] = []
    held: list[_StaleAfterAnOutage] = []

    def build(name: str, **kwargs: Any) -> epics.PV:
        built.append(name)
        if name == running and built.count(name) == 1:
            held.append(_StaleAfterAnOutage(name, **kwargs))
            return held[0]
        return real(name, **kwargs)

    monkeypatch.setattr(epics, "PV", build)

    driver = engine()
    driver.run(ROUTINE, {}, CITATION)
    held[0].stale = True
    ran = driver.run(ROUTINE, {}, CITATION)

    assert ran.cites == CITATION
    assert built.count(running) == 2
