"""Finding finished moves in the record, and recording arrivals in custody, over HTTP.

Two adapters against a keeper that is a double. `HttpTracking.moves` has
to tell a finished move from everything else an ended execution holds,
by either account of finishing, and read each procedure and operation
once rather than every pass. `HttpPlacing` has to ask custody page by
page and read a conflict as already recorded rather than as a fault.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from reporter.adapters.http_keeper import HttpPlacing, HttpTracking
from reporter.placing import Move
from reporter.seams import RefusedError
from tests._fakes import Answer, Sent

if TYPE_CHECKING:
    from collections.abc import Mapping

BASE = "http://keeper.test"
EXECUTION, PROCEDURE = uuid4(), uuid4()
MOVE_OPERATION, SCAN_OPERATION = uuid4(), uuid4()


@dataclass
class _Keeper:
    """Answers each read by its path and each write with a status, recording both."""

    reads: dict[str, Any]
    statuses: list[int] = field(default_factory=lambda: [204])
    sent: list[Sent] = field(default_factory=list[Sent])

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Answer:
        self.sent.append(Sent("GET", url, params=params, headers=headers))
        path = url.removeprefix(BASE)
        answer = self.reads[path]
        if isinstance(answer, dict) and "pages" in answer:
            return Answer(200, answer["pages"][(params or {}).get("cursor", "")])
        return Answer(200, answer)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Answer:
        self.sent.append(Sent("POST", url, json=json, headers=headers))
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return Answer(status, None, text="refused" if status >= 400 else "")

    def reads_of(self, path: str) -> int:
        return sum(1 for sent in self.sent if sent.method == "GET" and sent.url == BASE + path)


def _run(step_id: UUID, operation_id: UUID, **parameters: str) -> dict[str, Any]:
    return {
        "kind": "run",
        "step_id": str(step_id),
        "operation_id": str(operation_id),
        "parameters": parameters,
    }


def _step(procedure_step_id: UUID, outcome: str, engine_state: str | None = None) -> dict[str, Any]:
    return {
        "step_id": str(uuid4()),
        "procedure_step_id": str(procedure_step_id),
        "outcome": outcome,
        "engine_state": engine_state,
    }


def _record(*steps: tuple[dict[str, Any], dict[str, Any]]) -> _Keeper:
    """A keeper holding one ended execution whose steps run the given procedure steps."""
    return _Keeper(
        reads={
            "/executions": {"items": [{"execution_id": str(EXECUTION)}]},
            f"/executions/{EXECUTION}": {
                "execution_id": str(EXECUTION),
                "procedure_id": str(PROCEDURE),
                "steps": [step for step, _ in steps],
            },
            f"/procedures/{PROCEDURE}": {"steps": [run for _, run in steps]},
            f"/operations/{MOVE_OPERATION}": {"name": "move"},
            f"/operations/{SCAN_OPERATION}": {"name": "tomography_scan"},
        }
    )


def _a_move(outcome: str, engine_state: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    procedure_step = uuid4()
    run = _run(
        procedure_step, MOVE_OPERATION, path="results/a.h5/", **{"from": "alcf", "to": "19-bm"}
    )
    return _step(procedure_step, outcome, engine_state), run


def test_a_move_the_walk_finished_and_one_a_watcher_saw_complete_are_both_found() -> None:
    finished, completed = _a_move("Done"), _a_move("HandedOff", "Completed")
    keeper = _record(finished, completed)

    moves = HttpTracking(keeper, BASE, "token").moves()

    assert [str(move.step_id) for move in moves] == [
        finished[0]["step_id"],
        completed[0]["step_id"],
    ]
    assert (moves[0].path, moves[0].origin, moves[0].destination) == (
        "results/a.h5/",
        "alcf",
        "19-bm",
    )


@pytest.mark.parametrize(
    ("outcome", "engine_state"),
    [("HandedOff", "Running"), ("HandedOff", None), ("HandedOff", "Failed"), ("Broken", None)],
)
def test_a_move_still_running_failed_or_broken_is_not_found(
    outcome: str, engine_state: str | None
) -> None:
    keeper = _record(_a_move(outcome, engine_state))

    assert HttpTracking(keeper, BASE, "token").moves() == []


def test_a_step_running_another_operation_is_not_a_move() -> None:
    procedure_step = uuid4()
    scan = (_step(procedure_step, "Done"), _run(procedure_step, SCAN_OPERATION, path="x"))

    assert HttpTracking(_record(scan), BASE, "token").moves() == []


def test_a_procedure_and_an_operation_are_read_once_however_many_passes_ask() -> None:
    keeper = _record(_a_move("Done"))
    tracking = HttpTracking(keeper, BASE, "token")

    tracking.moves()
    tracking.moves()

    assert keeper.reads_of(f"/executions/{EXECUTION}") == 2
    assert keeper.reads_of(f"/procedures/{PROCEDURE}") == 1
    assert keeper.reads_of(f"/operations/{MOVE_OPERATION}") == 1


def _dataset(dataset_id: UUID, *refs: tuple[str, str]) -> dict[str, Any]:
    return {
        "dataset_id": str(dataset_id),
        "external_refs": [{"scheme": scheme, "value": value} for scheme, value in refs],
    }


def test_custody_is_asked_for_place_addresses_under_the_prefix_page_by_page() -> None:
    first, second = uuid4(), uuid4()
    keeper = _Keeper(
        reads={
            "/datasets": {
                "pages": {
                    "": {
                        "items": [
                            _dataset(
                                first,
                                ("place", "alcf:results/a.h5/"),
                                ("gpfs-file", "alcf:results/a.h5/"),
                            )
                        ],
                        "next_cursor": "page-2",
                    },
                    "page-2": {
                        "items": [_dataset(second, ("place", "alcf:results/b.h5/"))],
                        "next_cursor": None,
                    },
                }
            }
        }
    )

    found = HttpPlacing(keeper, keeper, BASE, "token").under("alcf:results/")

    assert found == [(first, "alcf:results/a.h5/"), (second, "alcf:results/b.h5/")]
    assert keeper.sent[0].params is not None
    assert keeper.sent[0].params["address_scheme"] == "place"
    assert keeper.sent[0].params["address_prefix"] == "alcf:results/"


def _a_finished_move() -> Move:
    return Move(
        execution_id=uuid4(),
        step_id=uuid4(),
        path="results/a.h5/",
        origin="alcf",
        destination="19-bm",
    )


def test_an_arrival_is_posted_with_the_move_as_the_work_that_made_the_copy() -> None:
    keeper, dataset_id, move = _Keeper(reads={}), uuid4(), _a_finished_move()

    news = HttpPlacing(keeper, keeper, BASE, "token").arrived(
        dataset_id, "19-bm:results/a.h5/", move
    )

    sent = keeper.sent[0]
    assert news is True
    assert sent.url == f"{BASE}/datasets/{dataset_id}/addresses"
    assert sent.json == {
        "external_ref": {"scheme": "place", "value": "19-bm:results/a.h5/"},
        "copied_by": {"execution_id": str(move.execution_id), "step_id": str(move.step_id)},
    }
    assert sent.headers is not None
    assert str(move.step_id) in sent.headers["Idempotency-Key"]


def test_an_address_the_dataset_already_holds_reads_as_already_recorded() -> None:
    keeper = _Keeper(reads={}, statuses=[409])

    news = HttpPlacing(keeper, keeper, BASE, "token").arrived(
        uuid4(), "19-bm:results/a.h5/", _a_finished_move()
    )

    assert news is False


def test_a_refusal_other_than_a_conflict_is_raised_rather_than_read_as_recorded() -> None:
    keeper = _Keeper(reads={}, statuses=[403])

    with pytest.raises(RefusedError):
        HttpPlacing(keeper, keeper, BASE, "token").arrived(
            uuid4(), "19-bm:results/a.h5/", _a_finished_move()
        )
