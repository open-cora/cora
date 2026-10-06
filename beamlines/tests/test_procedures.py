"""The procedure registers, and the two joins nothing else makes.

A procedure names an operation and claims records. Both of those live in
other files, and the keeper checks neither: it stores a beamline as
written, enforces no uniqueness across devices, and accepts any scope
string a caller sends. So the agreement between these three registers is
held here or nowhere.

## Why an unconfirmed procedure is tested for absence rather than shape

`confirmed` is a gate here rather than a note about evidence. An
unconfirmed procedure is never seeded, so the keeper never holds it and
nothing can dispatch it. That is the whole safety property, and it is
worth stating as a test because the word is borrowed from `devices.toml`
where it means something weaker.
"""

from pathlib import Path

import pytest

from descriptor import (
    DescriptorError,
    RunStep,
    load,
    load_operations,
    load_procedures,
    operations_from_mapping,
    procedures_from_mapping,
)

BEAMLINES = Path(__file__).parents[1]

EXPECTED_BEAMLINES = ("2-bm", "7-bm", "19-bm", "32-id")

PINNED_PROCEDURE_COUNTS = {
    "2-bm": 2,
    "7-bm": 2,
    "19-bm": 2,
    "32-id": 2,
}
"""Procedures each register is expected to carry, by beamline.

Pinned for the reason the device counts are pinned next door: every check
below ranges over these rows, and an empty register passes all of them
while verifying nothing.
"""


def _operation_names() -> set[str]:
    return {entry.name for entry in load_operations(BEAMLINES / "operations.toml").operations}


def _registered_refs(beamline: str) -> set[str]:
    return {device.ref for device in load(BEAMLINES / beamline / "devices.toml").devices}


def _namespaces(refs: set[str]) -> set[str]:
    return {ref.split(":", 1)[0] for ref in refs}


def test_every_beamline_carries_a_procedure_register() -> None:
    found = {path.name for path in BEAMLINES.iterdir() if (path / "procedures.toml").is_file()}
    assert found == set(EXPECTED_BEAMLINES)


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_a_register_names_the_beamline_whose_directory_it_sits_in(beamline: str) -> None:
    assert load_procedures(BEAMLINES / beamline / "procedures.toml").beamline == beamline


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_a_register_carries_the_procedures_it_is_pinned_at(beamline: str) -> None:
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    assert len(register.procedures) == PINNED_PROCEDURE_COUNTS[beamline]


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_every_run_step_names_an_operation_the_facility_register_holds(beamline: str) -> None:
    known = _operation_names()
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    for procedure in register.procedures:
        for step in procedure.steps:
            if isinstance(step, RunStep):
                assert step.operation in known, (
                    f"{beamline} runs {step.operation!r}, which beamlines/operations.toml "
                    f"does not hold. It holds {sorted(known)}"
                )


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_a_scope_in_the_beamlines_own_namespace_names_a_registered_device(beamline: str) -> None:
    """A claim on the beamline's own records has to be a claim on a known one.

    The rule is not that every scope is a registered device. A procedure
    driving a simulator claims a namespace this register deliberately does
    not hold, because what a deployment serves is the deployment's fact.

    The rule is that a scope reaching into a namespace the register does
    use has to name something the register holds. That is what separates
    `corasim19bm:`, which no registered device sits under, from
    `19bmSoft:aero:m99`, which looks exactly like a device at 19-BM and is
    not one.
    """
    refs = _registered_refs(beamline)
    owned = _namespaces(refs)
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    for procedure in register.procedures:
        for step in procedure.steps:
            scopes = step.scopes if isinstance(step, RunStep) else (step.record,)
            for scope in scopes:
                if scope.split(":", 1)[0] not in owned:
                    continue
                assert scope in refs, (
                    f"{beamline} claims {scope!r}, which is in a namespace its device "
                    "register uses and is not a device in it. A claim on this "
                    "beamline's own records has to name a registered one"
                )


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_a_register_confirms_at_most_one_procedure_of_each_name(beamline: str) -> None:
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    confirmed = [procedure.name for procedure in register.procedures if procedure.confirmed]
    assert len(confirmed) == len(set(confirmed))


def test_an_operation_named_with_a_space_is_refused() -> None:
    with pytest.raises(DescriptorError, match="whitespace"):
        operations_from_mapping({"operation": [{"name": "Tomography scan"}]})


def test_a_repeated_operation_name_is_refused() -> None:
    with pytest.raises(DescriptorError, match="repeats the name"):
        operations_from_mapping({"operation": [{"name": "tomography_scan"}] * 2})


def test_a_procedure_without_confirmed_is_refused() -> None:
    with pytest.raises(DescriptorError, match="needs confirmed"):
        procedures_from_mapping(
            {
                "beamline": "2-bm",
                "procedure": [
                    {"name": "Tomography scan", "step": [{"kind": "set", "record": "a:b", "to": 1}]}
                ],
            }
        )


def test_a_run_step_declaring_no_scopes_is_refused() -> None:
    with pytest.raises(DescriptorError, match="needs scopes"):
        procedures_from_mapping(
            {
                "beamline": "2-bm",
                "procedure": [
                    {
                        "name": "Tomography scan",
                        "confirmed": False,
                        "step": [{"kind": "run", "operation": "tomography_scan", "scopes": []}],
                    }
                ],
            }
        )


def test_a_step_of_an_unknown_kind_is_refused() -> None:
    with pytest.raises(DescriptorError, match="the kinds are"):
        procedures_from_mapping(
            {
                "beamline": "2-bm",
                "procedure": [
                    {"name": "Tomography scan", "confirmed": False, "step": [{"kind": "move"}]}
                ],
            }
        )


def test_a_second_confirmed_procedure_of_one_name_is_refused() -> None:
    row = {
        "name": "Tomography scan",
        "confirmed": True,
        "step": [{"kind": "run", "operation": "tomography_scan", "scopes": ["corasim2bmb:"]}],
    }
    with pytest.raises(DescriptorError, match="second confirmed"):
        procedures_from_mapping({"beamline": "2-bm", "procedure": [row, dict(row)]})
