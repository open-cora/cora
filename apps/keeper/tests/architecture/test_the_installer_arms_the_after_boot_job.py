"""The installer arms the job that brings the keeper back after its host reboots.

Without that job a deploy passes every check it runs and still does not
survive the next reboot of its host: the units are enabled, pinned and
lingering, and a user manager that started before the home was mounted
starts none of them. That happened once, and the keeper sat down for two
weeks with nothing reporting it.

So this pins the parts of `infra/deploy/install.sh` that arm the job and
the guard on it, because removing any of them leaves an installer that
reports success. The job's own behavior is tested beside this, against the
script.

## The guard's vocabulary

`queued-executions.sql` reads the event log by the names Execution writes
into it: a stream type, three event types and two payload keys. A rename on
the writing side would leave the query finding nothing, and a query finding
nothing is the one that lets the API start into a queue it was meant to
hold for. The integration tier runs the query against a real database;
this checks the names here, with no database, against the code that writes
them.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from keeper.execution.aggregates.execution import (
    EXECUTION_STREAM_TYPE,
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionParked,
    to_payload,
)

pytestmark = pytest.mark.architecture

_DEPLOY = Path(__file__).resolve().parents[2] / "infra" / "deploy"
_INSTALLER = _DEPLOY / "install.sh"
_GUARD = _DEPLOY / "nothing-is-queued.sh"
_QUERY = _DEPLOY / "queued-executions.sql"

_RENDERED = re.compile(r'"\$\{UNIT_DIR\}/([A-Za-z0-9._@-]+\.service)"')
"""A unit the installer writes, at the point it renders it."""

_ARM = re.compile(r'after-boot\.sh" arm ((?:[^\n]*\\\n)*[^\n]*)')
"""The arm call, with its continuation lines."""


def _text() -> str:
    return _INSTALLER.read_text(encoding="utf-8")


def _armed_words() -> list[str]:
    calls = _ARM.findall(_text())
    assert len(calls) == 1, (
        f"install.sh arms the after-boot job {len(calls)} times, and it has to be "
        "exactly once. None is a keeper that does not come back after a reboot; "
        "two is a crontab line written over itself in one deploy."
    )
    joined = calls[0].replace("\\\n", " ").removesuffix(')"')
    return [word.strip('"') for word in joined.split()]


def _rendered_units() -> list[str]:
    units = _RENDERED.findall(_text())
    assert len(units) >= 3, f"found {units}; the rule below is comparing against too little"
    return units


def test_the_installer_arms_the_job_for_every_unit_it_renders() -> None:
    words = _armed_words()
    armed = [word.split("=", 1)[0] for word in words[1:]]

    assert sorted(armed) == sorted(_rendered_units()), (
        f"install.sh renders {_rendered_units()} and arms the after-boot job for "
        f"{armed}. A unit left off comes back after a reboot only if somebody "
        "notices it did not."
    )


def test_only_the_api_is_armed_with_a_guard_and_it_is_the_queue_guard() -> None:
    guarded = {
        unit: guard
        for unit, _, guard in (word.partition("=") for word in _armed_words()[1:])
        if guard
    }
    api = [unit for unit in _rendered_units() if unit.endswith("keeper.service")]

    assert len(api) == 1
    assert guarded == {api[0]: "${SCRIPT_DIR}/nothing-is-queued.sh"}, (
        f"the after-boot job is armed with guards {guarded}. The API is the one "
        "unit whose return hands queued work to every conductor at once, so it "
        "is the one that waits for the queue to be empty, and the database and "
        "the JWKS have nothing to wait for."
    )


def test_the_guard_the_installer_names_ships_beside_it_and_is_executable() -> None:
    assert _GUARD.is_file()
    assert _GUARD.stat().st_mode & 0o111, (
        "the guard is not executable, so the job's check of it fails and the API "
        "is held after every reboot"
    )


def test_the_cron_check_comes_before_the_installer_changes_anything() -> None:
    text = _text()
    check = text.find('after-boot.sh" check')
    first_change = text.find('mkdir -p "${CORA_ROOT}"')

    assert check != -1, "install.sh never asks whether this host can run the job"
    assert first_change != -1
    assert check < first_change, (
        "install.sh asks whether cron can run the job only after it has started "
        "changing the host, so a refusal leaves half a deployment behind"
    )


def test_the_installer_refuses_when_the_guard_cannot_read_the_queue() -> None:
    """A guard that cannot read holds the API after every reboot, forever.

    That is the outage the job exists to end, so it has to fail the deploy
    that would arm it rather than surface at the next reboot. Exit 1 is
    not a refusal: work queued at deploy time is information, not a fault.
    """
    text = _text()
    assert 'if guard_said="$("${SCRIPT_DIR}/nothing-is-queued.sh")"; then' in text
    block = text[text.find('case "${guard}" in') :]
    assert re.search(r"^\s*0\) ;;$", block, re.M)
    assert re.search(r"^\s*1\) say ", block, re.M)
    assert re.search(r"^\s*\*\) die ", block, re.M)


def test_the_query_reads_the_stream_type_execution_writes() -> None:
    assert f"stream_type = '{EXECUTION_STREAM_TYPE}'" in _QUERY.read_text(encoding="utf-8")


def test_the_query_reads_the_event_types_execution_writes() -> None:
    query = _QUERY.read_text(encoding="utf-8")
    for written in (ExecutionDispatched, ExecutionClaimed, ExecutionParked, ExecutionEnded):
        assert f"'{written.__name__}'" in query, (
            f"queued-executions.sql does not name {written.__name__}, which is the "
            "event_type that event is stored under"
        )


def test_the_query_reads_payload_keys_the_dispatch_event_writes() -> None:
    payload = to_payload(
        ExecutionDispatched(
            execution_id=uuid4(),
            procedure_id=uuid4(),
            procedure_name="align_then_scan",
            beamline="2-bm",
            steps=[],
            routines=[],
            occurred_at=datetime.now(UTC),
        )
    )
    query = _QUERY.read_text(encoding="utf-8")
    for key in re.findall(r"payload ->> '([a-z_]+)'", query):
        assert key in payload, f"the query reads payload key {key!r}, which a dispatch never writes"
    assert re.findall(r"payload ->> '([a-z_]+)'", query), "the pattern above matched nothing"
