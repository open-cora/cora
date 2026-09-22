"""A write derives its claim and an acquisition has to declare one."""

from __future__ import annotations

import pytest

from conductor.claims import Claim, Scope
from conductor.procedure import Acquire, InvalidProcedureError, Move, Procedure, Set


def test_move_claims_the_record_it_moves() -> None:
    assert Move(record="2bmb:m1", to=3.0).claim == Claim(
        scopes=frozenset({Scope.record("2bmb:m1")})
    )


def test_move_given_a_field_claims_the_whole_record() -> None:
    assert Move(record="2bmb:m1.VAL", to=3.0).claim == Move(record="2bmb:m1", to=3.0).claim


def test_move_without_a_record_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Move(record="  ", to=1.0)


def test_set_claims_the_record_it_writes() -> None:
    """A configuration record is fought over the same way a motor is."""
    assert Set(record="2bmb:TomoScan:ScanType", to="Single").claim == Claim(
        scopes=frozenset({Scope.record("2bmb:TomoScan:ScanType")})
    )


def test_set_carries_a_choice_string_rather_than_an_index() -> None:
    """The vocabulary an engine compares against, not the one it stores."""
    assert Set(record="2bmb:TomoScan:ScanType", to="Single").to == "Single"


def test_set_carries_text_a_move_could_not() -> None:
    step = Set(record="2bmb:TomoScan:FileName", to="sample_042")
    assert "sample_042" in step.describes


def test_set_without_a_record_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Set(record="  ", to="Single")


def test_acquisition_declaring_no_devices_is_refused() -> None:
    """Nothing here can derive a plan's devices, so an author has to say."""
    with pytest.raises(InvalidProcedureError, match="must declare the devices"):
        Acquire(plan="tomo_scan", claim=Claim.nothing())


def test_acquisition_declaring_devices_is_built() -> None:
    step = Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1", "2bmb:cam1:"))
    assert step.claim.conflicts_with(Claim.over("2bmb:cam1:Acquire"))


def test_acquisition_without_a_plan_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Acquire(plan="", claim=Claim.over("2bmb:m1"))


def test_acquisition_without_a_bound_waits_indefinitely() -> None:
    """Unset is the patient default, which is why it is allowed to be unset."""
    assert Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1")).bound is None


def test_acquisition_says_its_bound_when_it_has_one() -> None:
    step = Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1"), bound=1200.0)
    assert "within 1200.0s" in step.describes


def test_acquisition_given_no_time_at_all_is_refused() -> None:
    """A bound of zero is an author's slip, not a request to run nothing."""
    with pytest.raises(InvalidProcedureError, match="no time at all"):
        Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1"), bound=0.0)


def test_procedure_without_steps_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name="align", steps=())


def test_procedure_without_a_name_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name=" ", steps=(Move(record="2bmb:m1", to=0.0),))
