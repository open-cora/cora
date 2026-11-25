"""Which datasets a finished move carried, and what one pass records for them.

`inside` is the rule for carried: the moved path itself, or anything under
it when the path names a folder, and never part of a folder. The pass is
checked against a custody that is a double, because what matters is which
datasets it asks to record where, and that a refusal for one move does
not stop the next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from reporter.placing import Move, inside, record_arrivals


def _move(
    path: str = "results/scan_0006.h5/", origin: str = "alcf", destination: str = "19-bm"
) -> Move:
    return Move(
        execution_id=uuid4(), step_id=uuid4(), path=path, origin=origin, destination=destination
    )


@dataclass
class _Custody:
    """Custody as a dictionary: which addresses each dataset holds, and what was recorded."""

    held: dict[UUID, list[str]] = field(default_factory=dict[UUID, list[str]])
    recorded: list[tuple[UUID, str, UUID]] = field(default_factory=list[tuple[UUID, str, UUID]])
    refusing: set[str] = field(default_factory=set[str])

    def under(self, prefix: str) -> list[tuple[UUID, str]]:
        if prefix in self.refusing:
            raise RuntimeError("not granted that command")
        return [
            (dataset_id, held)
            for dataset_id, addresses in self.held.items()
            for held in addresses
            if held.startswith(prefix)
        ]

    def arrived(self, dataset_id: UUID, held_at: str, move: Move) -> bool:
        if held_at in self.held.setdefault(dataset_id, []):
            return False
        self.held[dataset_id].append(held_at)
        self.recorded.append((dataset_id, held_at, move.step_id))
        return True


@pytest.mark.parametrize(
    ("held", "path", "expected"),
    [
        ("alcf:results/scan_0006.h5/", "results/scan_0006.h5/", "results/scan_0006.h5/"),
        (
            "alcf:results/scan_0006.h5/recon_00001.tiff",
            "results/scan_0006.h5/",
            "results/scan_0006.h5/recon_00001.tiff",
        ),
        ("alcf:raw/scan_0006.h5", "raw/scan_0006.h5", "raw/scan_0006.h5"),
        ("alcf:raw/scan_0006.h5.bak", "raw/scan_0006.h5", None),
        ("alcf:results/scan_0006.h5x/", "results/scan_0006.h5/", None),
        ("alcf:results/scan_0006.h5/", "results/scan_0006.h5/recon_00001.tiff", None),
        ("19-bm:results/scan_0006.h5/", "results/scan_0006.h5/", None),
    ],
    ids=[
        "the-folder-itself",
        "under-the-folder",
        "the-file-itself",
        "a-longer-name-is-not-the-file",
        "a-sibling-sharing-a-prefix",
        "part-of-a-folder",
        "another-place",
    ],
)
def test_an_address_counts_as_carried_only_when_it_lay_inside_what_moved(
    held: str, path: str, expected: str | None
) -> None:
    assert inside(held, _move(path=path)) == expected


def test_a_finished_folder_move_records_every_dataset_under_it_at_the_same_path() -> None:
    first, second, elsewhere = uuid4(), uuid4(), uuid4()
    custody = _Custody(
        held={
            first: ["alcf:results/a.h5/"],
            second: ["alcf:results/b.h5/"],
            elsewhere: ["alcf:raw/c.h5"],
        }
    )

    arrivals = record_arrivals([_move(path="results/")], custody)

    assert sorted(held_at for _, held_at, _ in custody.recorded) == [
        "19-bm:results/a.h5/",
        "19-bm:results/b.h5/",
    ]
    assert (arrivals.moves, arrivals.recorded, arrivals.already) == (1, 2, 0)


def test_the_arrival_names_the_move_as_the_work_that_made_the_copy() -> None:
    dataset_id = uuid4()
    custody = _Custody(held={dataset_id: ["alcf:results/scan_0006.h5/"]})
    move = _move()

    record_arrivals([move], custody)

    assert custody.recorded == [(dataset_id, "19-bm:results/scan_0006.h5/", move.step_id)]


def test_a_move_met_again_records_nothing_new_and_counts_what_was_already_there() -> None:
    custody = _Custody(held={uuid4(): ["alcf:results/scan_0006.h5/"]})
    move = _move()

    record_arrivals([move], custody)
    again = record_arrivals([move], custody)

    assert (again.recorded, again.already) == (0, 1)
    assert len(custody.recorded) == 1


def test_a_move_custody_holds_nothing_under_is_reported_as_unmatched() -> None:
    move = _move(path="logs/run_0006/")

    arrivals = record_arrivals([move], _Custody())

    assert arrivals.unmatched == (move,)
    assert arrivals.recorded == 0


def test_a_refusal_for_one_move_is_reported_and_the_next_move_is_still_recorded() -> None:
    dataset_id = uuid4()
    custody = _Custody(held={dataset_id: ["alcf:results/b.h5/"]}, refusing={"alcf:results/a.h5/"})
    refused, recorded = _move(path="results/a.h5/"), _move(path="results/b.h5/")

    arrivals = record_arrivals([refused, recorded], custody)

    assert [move for move, _ in arrivals.failed] == [refused]
    assert "not granted" in arrivals.failed[0][1]
    assert custody.recorded == [(dataset_id, "19-bm:results/b.h5/", recorded.step_id)]
