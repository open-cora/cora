"""A move derives its claim and a run has to declare one."""

from __future__ import annotations

import pytest

from conductor.claims import Claim, Scope
from conductor.procedure import InvalidProcedureError, Procedure, Run, Set


def test_a_set_claims_the_record_it_writes() -> None:
    assert Set(record="2bmb:m1", to=3.0).claim == Claim(scopes=frozenset({Scope.record("2bmb:m1")}))


def test_a_set_given_a_field_claims_the_whole_record() -> None:
    assert Set(record="2bmb:m1.VAL", to=3.0).claim == Set(record="2bmb:m1", to=3.0).claim


def test_a_set_without_a_record_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Set(record="  ", to=1.0)


def test_acquisition_declaring_no_devices_is_refused() -> None:
    """Nothing here can derive a plan's devices, so an author has to say."""
    with pytest.raises(InvalidProcedureError, match="must declare the devices"):
        Run(plan="tomo_scan", claim=Claim.nothing())


def test_acquisition_declaring_devices_is_built() -> None:
    step = Run(plan="tomo_scan", claim=Claim.over("2bmb:m1", "2bmb:cam1:"))
    assert step.claim.conflicts_with(Claim.over("2bmb:cam1:Run"))


def test_acquisition_without_a_plan_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Run(plan="", claim=Claim.over("2bmb:m1"))


def test_procedure_without_steps_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name="align", steps=())


def test_procedure_without_a_name_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name=" ", steps=(Set(record="2bmb:m1", to=0.0),))
