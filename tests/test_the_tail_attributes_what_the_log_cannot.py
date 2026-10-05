"""The tail's fold, which is the only part of it with a decision in it.

`tools/cora_tail.py` is mostly a loop around one HTTP call. The part worth
a test is the part the server deliberately does not do: deciding which
beamline an event belongs to, when only one event type in the whole log
carries a beamline.

Getting that wrong is quiet. An execution's steps would read as belonging
to no beamline, a `--beamline` filter would drop a running scan, and the
output would look like a slow day rather than a broken tail.

## Why these cases

Each one is a thing the log actually does. A dispatch names a beamline, a
claim does not, a Counsel event carries no beamline in any payload and
joins only by correlation, and a round opens before anything says where
it will run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

TREE_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = TREE_ROOT / "tools" / "cora_tail.py"


def _tail() -> Any:
    """Load the tail, which ships as a file to copy rather than a module."""
    spec = importlib.util.spec_from_file_location("_cora_tail_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _event(
    event_type: str,
    *,
    stream_type: str,
    stream_id: str,
    correlation_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "stream_type": stream_type,
        "stream_id": stream_id,
        "correlation_id": correlation_id,
        "occurred_at": "2026-10-04T14:02:11.000000Z",
        "payload": payload or {},
    }


def test_a_dispatch_attributes_its_own_execution() -> None:
    tail = _tail()
    known = tail.Attribution()
    execution_id, correlation_id = str(uuid4()), str(uuid4())
    dispatched = _event(
        "ExecutionDispatched",
        stream_type="Execution",
        stream_id=execution_id,
        correlation_id=correlation_id,
        payload={"execution_id": execution_id, "beamline": "7-bm"},
    )

    known.observe(dispatched)

    assert known.beamline_for(dispatched) == "7-bm"


def test_a_claim_carrying_no_beamline_is_attributed_by_its_stream() -> None:
    tail = _tail()
    known = tail.Attribution()
    execution_id = str(uuid4())
    known.observe(
        _event(
            "ExecutionDispatched",
            stream_type="Execution",
            stream_id=execution_id,
            correlation_id=str(uuid4()),
            payload={"execution_id": execution_id, "beamline": "2-bm"},
        )
    )

    claimed = _event(
        "ExecutionClaimed",
        stream_type="Execution",
        stream_id=execution_id,
        correlation_id=str(uuid4()),
    )

    assert known.beamline_for(claimed) == "2-bm"


def test_a_dataset_on_the_same_round_is_attributed_by_correlation() -> None:
    tail = _tail()
    known = tail.Attribution()
    execution_id, correlation_id = str(uuid4()), str(uuid4())
    known.observe(
        _event(
            "ExecutionDispatched",
            stream_type="Execution",
            stream_id=execution_id,
            correlation_id=correlation_id,
            payload={"execution_id": execution_id, "beamline": "19-bm"},
        )
    )

    registered = _event(
        "DatasetRegistered",
        stream_type="Dataset",
        stream_id=str(uuid4()),
        correlation_id=correlation_id,
    )

    assert known.beamline_for(registered) == "19-bm"


def test_a_pursuit_naming_its_beamline_attributes_its_own_rounds() -> None:
    tail = _tail()
    known = tail.Attribution()
    pursuit_id = str(uuid4())
    known.observe(
        _event(
            "PursuitStarted",
            stream_type="Pursuit",
            stream_id=pursuit_id,
            correlation_id=str(uuid4()),
            payload={"pursuit_id": pursuit_id, "beamline": "2-bm", "goal": "more contrast"},
        )
    )

    opened = _event(
        "PursuitRoundOpened",
        stream_type="Pursuit",
        stream_id=pursuit_id,
        correlation_id=str(uuid4()),
        payload={"round_index": 2},
    )

    assert known.beamline_for(opened) == "2-bm"


def test_a_registered_device_attributes_its_later_faults() -> None:
    tail = _tail()
    known = tail.Attribution()
    device_id = str(uuid4())
    known.observe(
        _event(
            "DeviceRegistered",
            stream_type="Device",
            stream_id=device_id,
            correlation_id=str(uuid4()),
            payload={"device_id": device_id, "beamline": "19-bm", "device_name": "rotation"},
        )
    )

    faulted = _event(
        "DeviceFaulted",
        stream_type="Device",
        stream_id=device_id,
        correlation_id=str(uuid4()),
    )

    assert known.beamline_for(faulted) == "19-bm"


def test_every_event_that_carries_a_beamline_is_one_that_opens_a_stream() -> None:
    """The set the fold keys on, stated so a fourth one cannot be forgotten
    quietly: an event type growing a beamline field and not named here
    leaves its whole stream reading as unattributed."""
    tail = _tail()
    assert {
        "ExecutionDispatched",
        "PursuitStarted",
        "DeviceRegistered",
    } == tail.OPENS_A_STREAM


def test_an_event_on_an_unseen_round_is_attributed_to_nothing() -> None:
    tail = _tail()
    known = tail.Attribution()

    opened = _event(
        "PursuitRoundOpened",
        stream_type="Pursuit",
        stream_id=str(uuid4()),
        correlation_id=str(uuid4()),
        payload={"round_index": 4},
    )

    assert known.beamline_for(opened) is None


def test_a_seeded_execution_attributes_steps_that_arrive_without_a_dispatch() -> None:
    """A tail started mid-scan never saw the dispatch, which is why it seeds."""
    tail = _tail()
    known = tail.Attribution()
    execution_id = str(uuid4())
    known.learn_stream(execution_id, "32-id")

    step = _event(
        "ExecutionStepDone",
        stream_type="Execution",
        stream_id=execution_id,
        correlation_id=str(uuid4()),
        payload={"step_index": 1},
    )

    assert known.beamline_for(step) == "32-id"


def test_a_dispatch_to_one_beamline_does_not_attribute_another_execution() -> None:
    tail = _tail()
    known = tail.Attribution()
    mine = str(uuid4())
    known.observe(
        _event(
            "ExecutionDispatched",
            stream_type="Execution",
            stream_id=mine,
            correlation_id=str(uuid4()),
            payload={"execution_id": mine, "beamline": "7-bm"},
        )
    )

    someone_elses = _event(
        "ExecutionClaimed",
        stream_type="Execution",
        stream_id=str(uuid4()),
        correlation_id=str(uuid4()),
    )

    assert known.beamline_for(someone_elses) is None


def test_an_unattributed_row_says_so_rather_than_naming_a_beamline() -> None:
    tail = _tail()
    row = tail.format_row(
        _event(
            "InquiryMade",
            stream_type="Inquiry",
            stream_id=str(uuid4()),
            correlation_id=str(uuid4()),
            payload={"objective": "raise the contrast"},
        ),
        None,
    )

    assert tail.UNATTRIBUTED in row
    assert "InquiryMade" in row
    assert "raise the contrast" in row


def test_a_row_shows_the_clock_and_the_beamline() -> None:
    tail = _tail()
    row = tail.format_row(
        _event(
            "ExecutionClaimed",
            stream_type="Execution",
            stream_id=str(uuid4()),
            correlation_id=str(uuid4()),
        ),
        "2-bm",
    )

    assert "14:02:11" in row
    assert "2-bm" in row
