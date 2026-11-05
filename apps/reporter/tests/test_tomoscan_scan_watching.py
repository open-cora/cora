"""How a scan that outlived its walk is asked after, and when it cannot be.

The other two far sides are services with queues: hand work over, keep
the id, ask about the id. TomoScan is a state machine in records holding
the scan it is running, so the reference is built out of what identifies
a scan and this is where that is taken apart again.

The case worth the most care is the one that returns nothing. A later
scan overwrites the ids, and a watcher that read the records without
comparing them would report a stranger's scan as this step's. That is
not a crash, it is a plausible answer to the wrong question, which is
the shape of mistake nothing downstream could catch.
"""

from __future__ import annotations

import pytest

from reporter.adapters.tomoscan_scans import TomoscanScans
from reporter.watching import UnknownWorkError

PREFIX = "corasim19bm:TomoScan:"
EXECUTION = "0199c0de-0000-7000-8000-000000000001"
STEP = "0199c0de-0000-7000-8000-000000000002"

OURS = f"tomoscan|{PREFIX}|{EXECUTION}|{STEP}"


def _server(execution: str = EXECUTION, step: str = STEP, scanning: str = "Done") -> TomoscanScans:
    records = {
        f"{PREFIX}KeeperExecutionId": execution,
        f"{PREFIX}KeeperStepId": step,
        f"{PREFIX}StartScan": scanning,
    }
    return TomoscanScans(read=lambda name: records[name])


def test_a_scan_the_server_has_finished_is_reported_completed() -> None:
    ended = _server().ending(OURS)

    assert ended is not None
    assert ended.report == "Completed"


def test_a_scan_the_server_is_still_running_is_left_for_the_next_pass() -> None:
    assert _server(scanning="1").ending(OURS) is None


def test_a_scan_whose_ids_a_later_scan_replaced_is_not_reported_as_that_one() -> None:
    """The failure this adapter exists to not have.

    The records hold whatever is running now. Reading them without
    comparing would answer about a different scan entirely, and answer
    confidently, which nothing downstream could tell from the truth.
    """
    superseded = _server(execution="0199c0de-0000-7000-8000-00000000000f", scanning="Done")

    assert superseded.ending(OURS) is None


def test_a_scan_whose_step_alone_was_replaced_is_also_refused() -> None:
    """Both ids are compared, not just the cheaper one.

    Two steps of one execution scanning in turn differ only here, and
    that is the pair most likely to collide in practice.
    """
    other_step = _server(step="0199c0de-0000-7000-8000-00000000000f", scanning="Done")

    assert other_step.ending(OURS) is None


def test_a_reference_from_another_far_side_is_not_recognised() -> None:
    """A Globus task id, which belongs to a different adapter entirely."""
    with pytest.raises(UnknownWorkError):
        _server().ending("d3510381-0000-0000-0000-000000000000")


def test_a_reference_of_this_scheme_but_the_wrong_shape_is_not_recognised() -> None:
    with pytest.raises(UnknownWorkError):
        _server().ending(f"tomoscan|{PREFIX}|{EXECUTION}")


def test_the_prefix_in_the_reference_is_what_is_read_rather_than_any_default() -> None:
    """A watcher serves a facility and the prefix is per station.

    Reading a configured default instead would answer about whichever
    beamline the watcher happened to be pointed at.
    """
    asked: list[str] = []

    def read(name: str) -> str:
        asked.append(name)
        return {"KeeperExecutionId": EXECUTION, "KeeperStepId": STEP}.get(
            name.rsplit(":", 1)[-1], "Done"
        )

    TomoscanScans(read=read).ending(f"tomoscan|7bmb:TomoScan:|{EXECUTION}|{STEP}")

    assert all(name.startswith("7bmb:TomoScan:") for name in asked)
