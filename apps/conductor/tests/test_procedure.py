"""A move derives its claim and a run has to declare one."""

from __future__ import annotations

import pytest

from conductor.claims import Claim, Scope
from conductor.procedure import InvalidProcedureError, Procedure, Step


def test_a_set_claims_the_record_it_writes() -> None:
    assert Step.setting(record="2bmb:m1", value=3.0).claim == Claim(
        scopes=frozenset({Scope.record("2bmb:m1")})
    )


def test_a_set_given_a_field_claims_the_whole_record() -> None:
    assert (
        Step.setting(record="2bmb:m1.VAL", value=3.0).claim
        == Step.setting(record="2bmb:m1", value=3.0).claim
    )


def test_a_set_without_a_record_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Step.setting(record="  ", value=1.0)


def test_acquisition_declaring_no_devices_is_refused() -> None:
    """Nothing here can derive a routine's devices, so an author has to say."""
    with pytest.raises(InvalidProcedureError, match="must declare what it touches"):
        Step(routine="tomo_scan", claim=Claim.nothing())


def test_acquisition_declaring_devices_is_built() -> None:
    step = Step(routine="tomo_scan", claim=Claim.over("2bmb:m1", "2bmb:cam1:"))
    assert step.claim.conflicts_with(Claim.over("2bmb:cam1:Run"))


def test_acquisition_without_a_plan_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Step(routine="", claim=Claim.over("2bmb:m1"))


def test_procedure_without_steps_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name="align", steps=())


def test_procedure_without_a_name_is_refused() -> None:
    with pytest.raises(InvalidProcedureError):
        Procedure(name=" ", steps=(Step.setting(record="2bmb:m1", value=0.0),))
