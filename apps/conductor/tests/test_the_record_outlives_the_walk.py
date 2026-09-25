"""A walk killed mid-step leaves behind the steps that finished.

This is the one promise `docs/reference/conducting.md` makes, and the
only way to check it is to kill something. A double that raised where a
signal would land would be checking that the code handles an exception,
which is not the question: the question is whether anything is on disk
when no code ran at all on the way out.

SIGKILL rather than SIGTERM for the same reason. A terminating signal
Python can see is one a future `finally` could quietly start relying on,
and a spike measured the case that offers no hook
at all. What survives here survives the worst of them.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests import _walker

if TYPE_CHECKING:
    from collections.abc import Iterator

WALKER = Path(_walker.__file__)

PATIENCE = 20.0
"""Seconds to wait for the walk to reach the step it never leaves."""


def _reports(journal: Path) -> list[dict[str, object]]:
    if not journal.exists():
        return []
    lines = journal.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def _wait_until_blocked(journal: Path, walk: subprocess.Popen[bytes]) -> list[dict[str, object]]:
    """Return once two steps are reported, or say what went wrong instead."""
    deadline = time.monotonic() + PATIENCE
    while time.monotonic() < deadline:
        reports = _reports(journal)
        if len([r for r in reports if r["report"] == "step_ended"]) == 2:
            return reports
        if walk.poll() is not None:
            raise AssertionError(f"the walk exited early with {walk.returncode}")
        time.sleep(0.05)
    raise AssertionError(f"the walk never reached its third step: {_reports(journal)}")


@pytest.fixture
def killed_walk(tmp_path: Path) -> Iterator[Path]:
    """Walk until the third step blocks, then SIGKILL and hand back the journal."""
    journal = tmp_path / "journal.jsonl"
    walk = subprocess.Popen([sys.executable, str(WALKER), str(journal)])
    try:
        _wait_until_blocked(journal, walk)
        walk.send_signal(signal.SIGKILL)
        walk.wait(timeout=10)
    finally:
        if walk.poll() is None:
            walk.kill()
            walk.wait(timeout=10)
    yield journal


def test_the_steps_that_finished_are_on_disk_after_the_process_is_gone(
    killed_walk: Path,
) -> None:
    ended = [r for r in _reports(killed_walk) if r["report"] == "step_ended"]
    assert [r["index"] for r in ended] == [0, 1]
    assert {r["outcome"] for r in ended} == {"Done"}


def test_the_step_it_died_in_was_never_reported(killed_walk: Path) -> None:
    """Nothing knows how that step ended, and the journal must not imply it does."""
    indices = [r["index"] for r in _reports(killed_walk) if r["report"] == "step_ended"]
    assert _walker.STEPS - 1 not in indices
    assert 2 not in indices


def test_nothing_is_reported_before_the_first_step_ends(killed_walk: Path) -> None:
    """A walk announces nothing on the way in, and used to.

    It reported its whole step list first, so that a reader looking at a
    prefix could tell a walk that finished early from one that stopped
    being heard from. The keeper holds that list now: it composes the
    procedure and writes every step onto the execution at dispatch,
    before anything is asked to drive it. Announcing it back would tell
    the record what it wrote.
    """
    assert [r["report"] for r in _reports(killed_walk)] == ["step_ended"] * 2


def test_no_ending_was_recorded_for_a_walk_that_did_not_end(killed_walk: Path) -> None:
    assert [r for r in _reports(killed_walk) if r["report"] == "walk_ended"] == []


def test_no_report_names_a_record_at_all(killed_walk: Path) -> None:
    """Every report used to carry the walk's own reference, because the
    walk was what opened the record. It is bound to an execution the keeper
    already wrote before `conduct` is called, so a step report is an
    index and nothing else."""
    assert all("reference" not in report for report in _reports(killed_walk))
