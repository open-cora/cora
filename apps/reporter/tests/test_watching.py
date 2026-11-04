"""Finishing the record of work that outlived the walk that started it.

Everything here runs against doubles, because `Watching` is written out
rather than imported and a far side is whatever a deployment hands over.

The case to read first is the one about a second pass. A watcher is a
loop, it will see the same finished task again, and the record it writes
the second time has to be the one it wrote the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from reporter.intents import ReportStepRun
from reporter.seams import DisagreedError
from reporter.watching import (
    AlreadyTold,
    Ending,
    Handover,
    Resolved,
    StillGoing,
    UnreadableLabelError,
    read_label,
    resolve,
)

ORIGIN = "watcher"


@dataclass
class _FarSide:
    """A service that answers with whatever ending it was handed."""

    ends: Ending | None = None

    def handovers(self) -> list[Handover]:
        return []

    def ending(self, reference: str) -> Ending | None:
        return self.ends


@dataclass
class _Record:
    """A keeper that takes reports, and can be told it already holds some."""

    disagrees_with: set[str] = field(default_factory=set[str])
    told: list[str] = field(default_factory=list[str])
    intents: list[ReportStepRun] = field(default_factory=list[ReportStepRun])

    def record(self, intent: ReportStepRun) -> None:
        if intent.reported in self.disagrees_with:
            raise DisagreedError(intent.reported)
        self.told.append(intent.reported)
        self.intents.append(intent)


def _handover() -> Handover:
    return Handover(reference="task-1", execution_id=uuid4(), step_id=uuid4())


def test_work_that_ended_well_is_reported_as_started_and_then_completed() -> None:
    """Both, and in that order, because the keeper refuses an ending it never saw begin."""
    record = _Record()

    outcome = resolve(_FarSide(ends=Ending("Completed")), record, _handover(), origin=ORIGIN)

    assert record.told == ["Started", "Completed"]
    assert outcome == Resolved(reference="task-1", report="Completed")


def test_work_that_ended_badly_is_reported_as_failed_rather_than_left_open() -> None:
    record = _Record()

    outcome = resolve(
        _FarSide(ends=Ending("Failed", "FILE_NOT_FOUND")), record, _handover(), origin=ORIGIN
    )

    assert record.told == ["Started", "Failed"]
    assert outcome == Resolved(reference="task-1", report="Failed")


def test_work_still_going_is_left_alone_rather_than_reported_as_anything() -> None:
    """A reconstruction takes hours and a watcher passes many times while it does."""
    record = _Record()

    outcome = resolve(_FarSide(ends=None), record, _handover(), origin=ORIGIN)

    assert record.told == []
    assert outcome == StillGoing(reference="task-1")


def test_a_second_pass_over_finished_work_writes_nothing_and_is_not_a_fault() -> None:
    """A watcher is a loop, so it sees every finished task again."""
    record = _Record(disagrees_with={"Started", "Completed"})

    outcome = resolve(_FarSide(ends=Ending("Completed")), record, _handover(), origin=ORIGIN)

    assert record.told == []
    assert outcome == AlreadyTold(reference="task-1")


def test_an_ending_is_written_even_where_the_start_was_already_known() -> None:
    """The half-finished case, which is what a watcher interrupted mid-report leaves."""
    record = _Record(disagrees_with={"Started"})

    outcome = resolve(_FarSide(ends=Ending("Completed")), record, _handover(), origin=ORIGIN)

    assert record.told == ["Completed"]
    assert outcome == Resolved(reference="task-1", report="Completed")


def test_every_report_carries_the_far_sides_name_for_the_work() -> None:
    """It is the join a store is later asked by, so it goes on each one."""
    record = _Record()
    handover = _handover()

    resolve(_FarSide(ends=Ending("Completed")), record, handover, origin=ORIGIN)

    assert [i.engine_reference for i in record.intents] == ["task-1", "task-1"]
    assert {i.execution_id for i in record.intents} == {handover.execution_id}
    assert {i.step_id for i in record.intents} == {handover.step_id}


def test_a_label_this_system_wrote_names_the_step_the_work_belongs_to() -> None:
    execution, step = uuid4(), uuid4()

    handover = read_label(f"cora {execution} {step}", "task-9")

    assert handover == Handover(reference="task-9", execution_id=execution, step_id=step)


@pytest.mark.parametrize(
    ("label", "because"),
    [
        ("nightly sync of /data", "somebody else's work"),
        ("cora", "no ids at all"),
        ("cora 1 2", "ids that are not ids"),
        (f"cora {UUID(int=1)}", "only one id"),
        (f"CORA {UUID(int=1)} {UUID(int=2)}", "the wrong prefix"),
    ],
    ids=["foreign", "bare", "not-ids", "one-id", "wrong-case"],
)
def test_a_label_this_system_did_not_write_is_refused_rather_than_guessed_at(
    label: str, because: str
) -> None:
    """Reporting against ids guessed from a near miss would write another execution's record."""
    with pytest.raises(UnreadableLabelError):
        read_label(label, "task-9")
