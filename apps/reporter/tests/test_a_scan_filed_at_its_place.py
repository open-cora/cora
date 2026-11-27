"""A scan filed inside a place is also recorded at its place address.

The address a scan engine reports is a path on the host that wrote it.
A move names data by place and path instead, and the watcher records an
arrival only for a dataset already holding a place address under what
moved. So a scan nobody gave a place address to is a scan no move can
carry, which is what these hold the session to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from reporter.intents import RegisterDataset, ReportStepRun
from reporter.outcomes import Kept
from reporter.seams import RefusedError, UnavailableError
from reporter.session import Session

PLACES = {"19-bm": "/data/cora/"}
INSIDE = "/data/cora/runs/p7/r1/scan_047.h5"
OUTSIDE = "/local1/scan_047.h5"


class _Reports:
    """Accepts every report, which is not what any of these are about."""

    def record(self, intent: ReportStepRun) -> None:
        _ = intent


@dataclass
class _Files:
    """Mints one id per dataset, remembers every place it was asked to record."""

    refusal: Exception | None = None
    dataset_id: UUID = field(default_factory=uuid4)
    placed: list[tuple[UUID, str]] = field(default_factory=list[tuple[UUID, str]])

    def record(self, intent: RegisterDataset) -> UUID:
        _ = intent
        return self.dataset_id

    def place(self, dataset_id: UUID, held_at: str) -> bool:
        if self.refusal is not None:
            raise self.refusal
        self.placed.append((dataset_id, held_at))
        return True


def _found(address: str) -> RegisterDataset:
    return RegisterDataset(
        execution_id=uuid4(),
        step_id=uuid4(),
        external_ref_value=address,
        occurred_at=datetime(2026, 11, 27, 10, 0, tzinfo=UTC),
        origin="a-scan",
    )


def test_a_scan_filed_inside_a_place_is_also_recorded_at_its_place_address() -> None:
    files = _Files()

    outcome = Session(_Reports(), files, places=PLACES).act(_found(INSIDE))

    assert isinstance(outcome, Kept)
    assert files.placed == [(files.dataset_id, "19-bm:runs/p7/r1/scan_047.h5")]
    assert outcome.placed == "19-bm:runs/p7/r1/scan_047.h5"
    assert outcome.external_ref_value == INSIDE


def test_a_scan_filed_outside_every_place_is_recorded_at_none() -> None:
    files = _Files()

    outcome = Session(_Reports(), files, places=PLACES).act(_found(OUTSIDE))

    assert isinstance(outcome, Kept)
    assert files.placed == []
    assert outcome.placed is None


def test_a_session_given_no_places_records_no_place_address() -> None:
    files = _Files()

    outcome = Session(_Reports(), files).act(_found(INSIDE))

    assert isinstance(outcome, Kept)
    assert files.placed == []


def test_a_refused_place_address_is_a_reason_on_the_outcome_and_the_dataset_stays_kept() -> None:
    files = _Files(refusal=RefusedError("POST /datasets/x/addresses: 403"))

    outcome = Session(_Reports(), files, places=PLACES).act(_found(INSIDE))

    assert isinstance(outcome, Kept)
    assert outcome.placed is None
    assert outcome.unplaced is not None
    assert "19-bm:runs/p7/r1/scan_047.h5" in outcome.unplaced


def test_an_unreachable_place_address_asks_for_the_delivery_again() -> None:
    """Filing and placing both answer a repeat with what they answered first."""
    files = _Files(refusal=UnavailableError("POST /datasets/x/addresses: timed out"))

    with pytest.raises(UnavailableError):
        Session(_Reports(), files, places=PLACES).act(_found(INSIDE))
