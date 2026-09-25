"""A walk holds each claim for one step, stops where one does not finish, and says so."""

from __future__ import annotations

import pytest

from conductor.claims import Claim, Ledger
from conductor.conduct import conduct
from conductor.outcomes import Broke, Done, Refused, Skipped
from conductor.procedure import Acquire, Move, Procedure
from tests._fakes import (
    CollectingRecording,
    RecordingAcquisition,
    RecordingControl,
    RecordingRefusedError,
)


def _procedure() -> Procedure:
    return Procedure(
        name="align_then_scan",
        steps=(
            Move(record="2bmb:m1", to=0.0),
            Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1", "2bmb:cam1:")),
            Move(record="2bmb:m2", to=5.0),
        ),
    )


def test_walk_over_free_hardware_finishes_every_step() -> None:
    control, engine = RecordingControl(), RecordingAcquisition()
    walk = conduct(_procedure(), control=control, acquisition=engine)
    assert walk.finished
    assert walk.tally() == {"Done": 3}
    assert control.moves == [("2bmb:m1", 0.0), ("2bmb:m2", 5.0)]


def test_walk_carries_a_minted_reference_into_the_engine() -> None:
    engine = RecordingAcquisition()
    conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=engine,
        mint=lambda: "directive-1",
    )
    plan, _, reference = engine.asked[0]
    assert (plan, reference) == ("tomo_scan", "directive-1")


def test_walk_keeps_what_the_engine_said_without_reading_it() -> None:
    engine = RecordingAcquisition(says="success")
    walk = conduct(_procedure(), control=RecordingControl(), acquisition=engine)
    acquired = [o.acquired for o in walk.outcomes if isinstance(o, Done) and o.acquired]
    assert acquired[0].said == "success"
    assert acquired[0].engine_reference == f"engine-uid-for-{acquired[0].reference}"


def test_walk_releases_a_claim_so_a_later_step_can_take_it() -> None:
    ledger = Ledger()
    walk = conduct(
        _procedure(), control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger
    )
    assert walk.finished
    assert ledger.holders() == frozenset()


def test_walk_is_refused_where_another_holder_has_the_hardware() -> None:
    ledger = Ledger()
    ledger.acquire("somebody_else", Claim.over("2bmb:m1.RBV"))
    walk = conduct(
        _procedure(), control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger
    )
    assert not walk.finished
    first = walk.outcomes[0]
    assert isinstance(first, Refused)
    assert first.holder == "somebody_else"


def test_walk_refused_at_its_first_step_skips_the_rest() -> None:
    ledger = Ledger()
    ledger.acquire("somebody_else", Claim.over("2bmb:m1"))
    walk = conduct(
        _procedure(), control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger
    )
    assert walk.tally() == {"Refused": 1, "Skipped": 2}


def test_walk_does_not_ask_the_engine_for_a_step_it_never_reached() -> None:
    ledger = Ledger()
    ledger.acquire("somebody_else", Claim.over("2bmb:m1"))
    engine = RecordingAcquisition()
    conduct(_procedure(), control=RecordingControl(), acquisition=engine, ledger=ledger)
    assert engine.asked == []


def test_walk_stops_where_a_seam_raises_and_keeps_the_cause() -> None:
    control = RecordingControl(breaks_on="2bmb:m1")
    walk = conduct(_procedure(), control=control, acquisition=RecordingAcquisition())
    broke = walk.outcomes[0]
    assert isinstance(broke, Broke)
    assert "TimeoutError" in broke.cause
    assert walk.tally() == {"Broke": 1, "Skipped": 2}


def test_walk_releases_the_claim_of_a_step_that_broke() -> None:
    ledger = Ledger()
    conduct(
        _procedure(),
        control=RecordingControl(breaks_on="2bmb:m1"),
        acquisition=RecordingAcquisition(),
        ledger=ledger,
    )
    assert ledger.holders() == frozenset()


def test_walk_stops_where_the_engine_raises() -> None:
    walk = conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(breaks_on="tomo_scan"),
    )
    assert walk.tally() == {"Done": 1, "Broke": 1, "Skipped": 1}


def test_walk_stops_where_the_engine_did_not_carry_the_reference() -> None:
    """The join is the minted reference, and nothing downstream could notice."""
    walk = conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(answers_with="the-engines-own-id"),
    )
    broke = walk.outcomes[1]
    assert isinstance(broke, Broke)
    assert "ReferenceNotCarriedError" in broke.cause
    assert walk.tally() == {"Done": 1, "Broke": 1, "Skipped": 1}


def test_two_walks_sharing_a_ledger_do_not_both_get_one_motor() -> None:
    """The reason a ledger is passed in rather than made: it is what joins them."""
    ledger = Ledger()
    held = Procedure(name="holder", steps=(Move(record="2bmb:m1", to=1.0),))
    conduct(held, control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger)
    ledger.acquire("a_scan_still_running", Claim.over("2bmb:m1"))
    second = conduct(
        _procedure(), control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger
    )
    assert isinstance(second.outcomes[0], Refused)


def test_skipped_steps_are_reported_rather_than_left_out() -> None:
    ledger = Ledger()
    ledger.acquire("somebody_else", Claim.over("2bmb:m1"))
    walk = conduct(
        _procedure(), control=RecordingControl(), acquisition=RecordingAcquisition(), ledger=ledger
    )
    assert len(walk.outcomes) == 3
    assert [type(o).__name__ for o in walk.outcomes] == ["Refused", "Skipped", "Skipped"]
    assert isinstance(walk.outcomes[2], Skipped)


def test_a_walk_says_nothing_until_its_first_step_has_ended() -> None:
    """It announced its whole step list first, and no longer needs to.

    The reason was that a reader given only a prefix cannot tell a walk
    that finished early from one that stopped being heard from. AROC
    holds the list now, written onto the execution at dispatch, so
    sending it back would tell the record what it wrote.
    """
    told = CollectingRecording()
    conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(),
        reporting=told,
    )
    assert told.order[0] == "step_ended"


def test_a_walk_reports_each_outcome_as_its_step_ends() -> None:
    told = CollectingRecording()
    conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(),
        reporting=told,
    )
    assert [index for index, _ in told.stepped] == [0, 1, 2]
    assert all(isinstance(outcome, Done) for _, outcome in told.stepped)
    assert told.order == ["step_ended", "step_ended", "step_ended", "walk_ended"]


def test_a_walk_reports_the_steps_it_skipped_as_well_as_the_ones_it_ran() -> None:
    """The record has to show the whole procedure, not the part that happened."""
    ledger = Ledger()
    ledger.acquire("somebody_else", Claim.over("2bmb:m1"))
    told = CollectingRecording()
    conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(),
        ledger=ledger,
        reporting=told,
    )
    assert [type(outcome).__name__ for _, outcome in told.stepped] == [
        "Refused",
        "Skipped",
        "Skipped",
    ]
    assert told.ended


def test_a_walk_reports_one_ending_and_only_one() -> None:
    """Nothing here names a record any more.

    A report used to carry the walk's own reference, because the walk
    was what opened the record. It is bound before `conduct` is called
    now, so a step report is an index and an ending is a fact with no
    arguments at all.
    """
    told = CollectingRecording()
    walk = conduct(
        _procedure(),
        control=RecordingControl(),
        acquisition=RecordingAcquisition(),
        reporting=told,
        mint=lambda: "carried-into-the-engine",
    )
    assert walk.reference == "carried-into-the-engine"
    assert told.ended == 1


def test_a_walk_stops_where_nothing_can_be_told_about_it() -> None:
    """An adapter that means to survive an outage swallows its own."""
    told = CollectingRecording(refuses_step=1)
    with pytest.raises(RecordingRefusedError):
        conduct(
            _procedure(),
            control=RecordingControl(),
            acquisition=RecordingAcquisition(),
            reporting=told,
        )
    assert told.ended == 0


def test_a_recording_failure_is_not_recorded_as_the_step_breaking() -> None:
    """The move arrived. Only the telling failed, and Broke would say otherwise."""
    control = RecordingControl()
    told = CollectingRecording(refuses_step=0)
    with pytest.raises(RecordingRefusedError):
        conduct(_procedure(), control=control, acquisition=RecordingAcquisition(), reporting=told)
    assert control.moves == [("2bmb:m1", 0.0)]
    assert told.stepped == []


def test_a_walk_told_of_no_recording_still_returns_everything_it_did() -> None:
    walk = conduct(_procedure(), control=RecordingControl(), acquisition=RecordingAcquisition())
    assert walk.finished
    assert walk.tally() == {"Done": 3}
    assert walk.reference
