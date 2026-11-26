"""The TomoScan engine adapter, driven against a soft IOC shaped like one.

`tests/_tomoscan_ioc.py` says what it does and does not imitate. What
matters for reading these is that starting is not instant there, so a
wait for the scan to begin is a wait that can fail.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import epics
import pytest

from conductor.adapters.tomoscan_engine import (
    EngineNotConfiguredError,
    EngineNotRunningError,
    PlacementNotHonouredError,
    ScanDidNotFinishError,
    ScanDidNotStartError,
    SettingsRefusedError,
    SetupNotCarriedError,
    TomoscanEngine,
    UnknownRoutineError,
    UnreachableEngineError,
)
from conductor.seams import APPLIED_SETUP, Citation, ReferenceNotCarriedError, WorkHandedOffError
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
        "running_timeout": 1.0,
    }
    settings.update(overrides)
    return TomoscanEngine(**settings)  # type: ignore[arg-type]


def wait_until_quiet(settle: float = 0.5, limit: float = 20.0) -> None:
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

    `settle` has to be longer than the sim's own pause between writes,
    which is `_tomoscan_ioc.SETTLE_SECONDS`. It was the same 0.3, so a
    scan pausing between two of its writes looked exactly like a scan
    that had finished, and this returned into the middle of one. That
    went unnoticed while no test left a scan running past itself.
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
    """Undo whatever the last test set, so each starts from a served scan.

    The citation records are cleared with a space, for the reason
    `CLEARED` gives: an empty string is a write the server ignores, so
    the last test's ids would otherwise survive into this one.
    """
    wait_until_quiet()
    for suffix, value in (
        ("ServerRunning", "Running"),
        ("RefuseToStart", 0),
        ("DropCitation", 0),
        ("ReturnAtOnce", 0),
        ("KeeperExecutionId", " "),
        ("KeeperStepId", " "),
        ("CameraPVPrefix", "conductor-camera-test:"),
        ("FilePluginPVPrefix", "conductor-camera-test:HDF1:"),
        ("NumAngles", 1500),
        ("NumFlatFields", 10),
        ("FlatFieldMode", "Start"),
        ("SampleName", "before"),
    ):
        epics.caput(f"{_tomoscan_ioc.PREFIX}{suffix}", value, wait=True, timeout=10)


SETUP = "tomo-test"


def collecting(settings: dict[str, object], **step: object) -> dict[str, object]:
    """A step's parameters as the work intake hands them over for a setup."""
    applied = {"name": SETUP, "revision": 1, "settings": settings}
    return {"config": SETUP, **step, APPLIED_SETUP: applied}


def record(suffix: str, *, as_string: bool = False) -> Any:
    """One test record, read past the monitor cache for the reason `blank` gives."""
    return epics.PV(f"{_tomoscan_ioc.PREFIX}{suffix}").get(as_string=as_string, use_monitor=False)


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


def test_a_setup_reaches_every_record_it_names_and_the_step_parameters_none() -> None:
    settings: dict[str, object] = {"NumAngles": 720, "FlatFieldMode": "Both", "SampleName": "monet"}

    ran = engine().run(ROUTINE, collecting(settings, override={"NumAngles": 720}), CITATION)

    assert ran.cites == CITATION
    assert record("NumAngles") == 720
    assert record("FlatFieldMode", as_string=True) == "Both"
    assert record("SampleName", as_string=True) == "monet"


def test_a_choice_may_be_given_by_its_position_among_the_records_choices() -> None:
    engine().run(ROUTINE, collecting({"FlatFieldMode": 2}), CITATION)
    assert record("FlatFieldMode", as_string=True) == "Both"


def test_a_record_publishing_no_limits_takes_any_number() -> None:
    engine().run(ROUTINE, collecting({"ExposureTime": 12345.0}), CITATION)
    assert record("ExposureTime") == pytest.approx(12345.0)


def test_a_step_naming_a_setup_without_its_settings_is_refused_and_writes_nothing() -> None:
    with pytest.raises(SetupNotCarriedError) as refused:
        engine().run(ROUTINE, {"config": SETUP, "NumAngles": 4242}, CITATION)
    assert refused.value.named == SETUP
    assert record("NumAngles") == 1500


@pytest.mark.parametrize(("asked", "value"), [("at", "alcf"), ("output", "scans/")])
def test_a_step_asking_where_its_data_lands_is_refused_and_writes_nothing(
    asked: str, value: str
) -> None:
    with pytest.raises(PlacementNotHonouredError) as refused:
        engine().run(ROUTINE, collecting({"NumAngles": 4242}, **{asked: value}), CITATION)
    assert refused.value.asked == (asked,)
    assert record("NumAngles") == 1500


@pytest.mark.parametrize(
    ("settings", "misfit"),
    [
        ({"NumFlatFields": 500}, "outside this record's limits"),
        ({"FlatFieldMode": "Sometimes"}, "not one of"),
        ({"FlatFieldMode": 9}, "not one of"),
        ({"ExposureTime": "fast"}, "which is text, and this record holds a number"),
        ({"SampleName": 5}, "which is not text"),
        ({"NumAngles": 900.5}, "not whole"),
        ({"NumAngles": True}, "which is a bool"),
        ({"NumAngels": 16}, "no record here answers to"),
    ],
)
def test_a_setting_the_server_would_not_take_is_refused_and_nothing_is_written(
    settings: dict[str, object], misfit: str
) -> None:
    with pytest.raises(SettingsRefusedError) as refused:
        engine(connect_timeout=1.0).run(
            ROUTINE, collecting({"SampleName": "after", **settings}), CITATION
        )
    (named,) = refused.value.misfits
    assert misfit in named
    assert record("SampleName", as_string=True) == "before"
    assert record("KeeperExecutionId", as_string=True).strip() != CITATION.execution_id


def test_every_setting_the_server_would_not_take_is_named_at_once() -> None:
    with pytest.raises(SettingsRefusedError) as refused:
        engine().run(
            ROUTINE, collecting({"NumAngles": 900.5, "FlatFieldMode": "Sometimes"}), CITATION
        )
    assert [misfit.split(" = ")[0] for misfit in refused.value.misfits] == [
        "NumAngles",
        "FlatFieldMode",
    ]


def test_parameters_that_are_not_a_setup_are_checked_against_the_server_too() -> None:
    with pytest.raises(SettingsRefusedError):
        engine().run(ROUTINE, {"NumFlatFields": 500, "NumAngles": 4242}, CITATION)
    assert record("NumAngles") == 1500


def test_a_server_that_is_not_running_is_refused() -> None:
    epics.caput(f"{_tomoscan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)
    with pytest.raises(EngineNotRunningError) as refused:
        engine().run(ROUTINE, {}, CITATION)
    assert refused.value.said == "Stopped"


def test_a_server_that_stops_briefly_and_returns_is_not_refused() -> None:
    """A real server reads stopped while it writes angles, with nothing wrong.

    The record is fed by a watchdog thread that the server starves itself
    whenever it holds the interpreter lock through an HDF5 call, so a
    single read at the wrong moment refuses a station that is working.
    """
    epics.caput(f"{_tomoscan_ioc.PREFIX}ServerRunning", "Stopped", wait=True, timeout=10)

    def restore() -> None:
        time.sleep(0.3)
        epics.caput(f"{_tomoscan_ioc.PREFIX}ServerRunning", "Running", wait=True, timeout=10)

    waking = threading.Thread(target=restore)
    waking.start()
    try:
        ran = engine(running_timeout=10.0).run(ROUTINE, {}, CITATION)
    finally:
        waking.join()
    assert ran.cites == CITATION


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


class _HearsOnlyItsFirstUpdate(epics.PV):
    """A channel that hears its record once and then nothing more.

    Standing in for an update still on its way. pyepics sizes a read by
    the last update its channel heard, even a read that skips the cache,
    so a record that has grown since is read at its old length until the
    news arrives. Landing a read inside that window by racing a server
    is a test that passes on a fast machine, so this channel is held in
    it instead.

    The first update is waited for before the channel stops listening,
    because a channel that heard nothing reads in full and would make
    the test holding it prove nothing.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._first = threading.Event()
        self._listening = True
        super().__init__(*args, callback=self._hear, **kwargs)

    def _hear(self, **_: Any) -> None:
        self._first.set()

    def wait_for_connection(self, timeout: float | None = None) -> bool:
        connected = bool(super().wait_for_connection(timeout=timeout))
        if connected and self._listening:
            self._listening = False
            self._first.wait(timeout=5.0)
            self.clear_auto_monitor()
        return connected


def held_at_its_first_update(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> list[_HearsOnlyItsFirstUpdate]:
    """Hand the engine a channel to this record that hears it once, and keep it.

    Only the first channel built for the record is held, so a read the
    test makes afterwards reaches the server like any other.
    """
    name = f"{_tomoscan_ioc.PREFIX}{suffix}"
    real = epics.PV
    held: list[_HearsOnlyItsFirstUpdate] = []

    def build(pvname: str, **kwargs: Any) -> epics.PV:
        if pvname != name or held:
            return real(pvname, **kwargs)
        held.append(_HearsOnlyItsFirstUpdate(pvname, **kwargs))
        return held[0]

    monkeypatch.setattr(epics, "PV", build)
    return held


def test_a_status_longer_than_the_last_update_heard_is_said_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Held after "Scanning", eight characters, a read asked for eight and got "Scan com"."""
    epics.caput(f"{_tomoscan_ioc.PREFIX}ScanStatus", "Scanning", wait=True, timeout=10)
    held = held_at_its_first_update(monkeypatch, "ScanStatus")

    ran = engine().run(ROUTINE, {}, CITATION)

    assert held[0].count == len("Scanning")
    assert ran.said == "Scan complete"


def test_a_text_record_holding_a_blank_still_takes_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank is one character, and a character record of one element holds a number."""
    epics.caput(f"{_tomoscan_ioc.PREFIX}SampleName", " ", wait=True, timeout=10)
    held = held_at_its_first_update(monkeypatch, "SampleName")

    engine().run(ROUTINE, collecting({"SampleName": "monet"}), CITATION)

    assert held[0].count == len(" ")
    assert record("SampleName", as_string=True) == "monet"


def test_a_scan_still_running_at_the_bound_is_handed_over_rather_than_broken() -> None:
    """What a station taking an hour-long scan needs the record to say.

    Nothing here stops the scan. It was a refusal until 19-BM was
    measured finishing one eighteen seconds inside the bound, which
    meant the record said a step broke while the beamline went on and
    got its data, kept for good because a procedure is append-only.
    """
    epics.caput(f"{_tomoscan_ioc.PREFIX}ReturnAtOnce", 1, wait=True, timeout=10)
    try:
        with pytest.raises(WorkHandedOffError) as handed:
            engine(scan_timeout=0.2).run(ROUTINE, {}, CITATION)
    finally:
        epics.caput(f"{_tomoscan_ioc.PREFIX}ReturnAtOnce", 0, wait=True, timeout=10)
        wait_until_quiet()

    assert handed.value.reference.startswith(f"tomoscan|{_tomoscan_ioc.PREFIX}|")
    assert CITATION.execution_id in handed.value.reference
    assert CITATION.step_id in handed.value.reference


def test_a_scan_handed_over_without_a_citation_is_refused_instead() -> None:
    """A handoff nobody can resolve is worse than a wrong ending.

    The ids are what a watcher compares against the server's records to
    know the scan it finds is the one it was asked about. Without them
    the reference names a prefix and nothing else, and the step would
    stay open for good.
    """
    epics.caput(f"{_tomoscan_ioc.PREFIX}ReturnAtOnce", 1, wait=True, timeout=10)
    try:
        with pytest.raises(ScanDidNotFinishError):
            engine(scan_timeout=0.2).run(ROUTINE, {}, None)
    finally:
        epics.caput(f"{_tomoscan_ioc.PREFIX}ReturnAtOnce", 0, wait=True, timeout=10)
        wait_until_quiet()


def test_the_station_is_the_prefix_up_to_its_first_separator() -> None:
    """What a claim at the same beamline would share with the scan server.

    `19bm:TomoScan:` is served by the station that serves `19bm:det:`,
    so comparing a claim against the whole prefix would refuse every
    honest row at the beamline: no procedure claims the scan server.
    """
    built = TomoscanEngine(prefix="19bm:TomoScan:", routines=frozenset({ROUTINE}))

    assert built.station == "19bm:"


def test_a_simulator_prefix_gives_a_station_the_real_one_does_not_cover() -> None:
    """The pair this facility actually ran, which nothing compared.

    A procedure claiming corasim19bm: and a conductor driving
    19bm:TomoScan: disagree, and the disagreement has to be visible
    here or the walk cannot refuse it.
    """
    simulated = TomoscanEngine(prefix="corasim19bm:TomoScan:", routines=frozenset({ROUTINE}))
    station = TomoscanEngine(prefix="19bm:TomoScan:", routines=frozenset({ROUTINE}))

    assert simulated.station == "corasim19bm:"
    assert not "corasim19bm:".startswith(station.station)


def test_a_prefix_with_no_separator_is_its_own_station() -> None:
    """Nothing says a control system spells names this way.

    Taking everything before a separator that is not there would give
    an empty station, which covers every claim ever written.
    """
    odd = TomoscanEngine(prefix="scanserver", routines=frozenset({ROUTINE}))

    assert odd.station == "scanserver"
