"""The reference rule, and the register that has to keep it."""

from pathlib import Path

import pytest
from descriptor import DescriptorError, from_mapping, load, normalize_reference

TWO_BM = Path(__file__).parents[1] / "2-bm" / "devices.toml"

EXPECTED_2BM_DEVICE_COUNT = 0
"""Devices the 2-BM register is expected to carry.

Zero is the honest state, not a placeholder. The rows come from a caget
sweep against 2-BM's own IOCs or from staff, and until somebody has run
one there is nothing to write down.

It is pinned for the reason `test_fitness_scope.py` pins its counts: the
check below that every reference is in normal form ranges over this file,
and with no rows in it that check passes while verifying nothing. Raise
this deliberately, in the commit that adds the rows.
"""


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2bmb:m1", "2bmb:m1"),
        ("2bmb:m1.RBV", "2bmb:m1"),
        ("2bmb:m1.VAL", "2bmb:m1"),
        ("2bmb:m1:", "2bmb:m1"),
        ("  2bmb:m1.RBV  ", "2bmb:m1"),
        ("2bm:MCTOptics:LensSelect", "2bm:MCTOptics:LensSelect"),
        ("2bmb:m1.DRVH.SEVR", "2bmb:m1"),
    ],
)
def test_normalize_reference_reduces_an_address_to_its_record(given: str, expected: str) -> None:
    assert normalize_reference(given) == expected


def test_normalize_reference_keeps_two_similarly_named_motors_apart() -> None:
    assert normalize_reference("2bmb:m1") != normalize_reference("2bmb:m10")


@pytest.mark.parametrize("given", ["", "   ", ".RBV", ":", "  :  "])
def test_normalize_reference_refuses_an_address_naming_no_record(given: str) -> None:
    with pytest.raises(DescriptorError):
        normalize_reference(given)


def test_from_mapping_refuses_a_reference_not_already_in_normal_form() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [{"ref": "2bmb:m1.RBV", "name": "Sample rotation", "confirmed": True}],
    }
    with pytest.raises(DescriptorError, match="'2bmb:m1'"):
        from_mapping(settings)


def test_from_mapping_refuses_two_rows_at_one_address() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [
            {"ref": "2bmb:m1", "name": "Sample rotation", "confirmed": True},
            {"ref": "2bmb:m1", "name": "Rotation, again", "confirmed": False},
        ],
    }
    with pytest.raises(DescriptorError, match="repeats the reference"):
        from_mapping(settings)


def test_from_mapping_refuses_a_field_no_keeper_command_accepts() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [
            {
                "ref": "2bmb:m1",
                "name": "Sample rotation",
                "confirmed": True,
                "family": "RotaryStage",
            }
        ],
    }
    with pytest.raises(DescriptorError, match="family"):
        from_mapping(settings)


def test_from_mapping_refuses_a_row_that_does_not_say_whether_it_was_confirmed() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [{"ref": "2bmb:m1", "name": "Sample rotation"}],
    }
    with pytest.raises(DescriptorError, match="confirmed"):
        from_mapping(settings)


def test_from_mapping_accepts_a_well_formed_register() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [{"ref": "2bmb:m1", "name": "  Sample rotation  ", "confirmed": False}],
    }
    register = from_mapping(settings)
    assert register.scheme == "epics-record"
    assert register.devices[0].name == "Sample rotation"
    assert register.devices[0].confirmed is False


def test_the_2bm_register_loads() -> None:
    assert load(TWO_BM).scheme == "epics-record"


def test_the_2bm_register_carries_the_pinned_number_of_devices() -> None:
    assert len(load(TWO_BM).devices) == EXPECTED_2BM_DEVICE_COUNT


def test_every_2bm_reference_is_already_in_normal_form() -> None:
    for entry in load(TWO_BM).devices:
        assert entry.ref == normalize_reference(entry.ref)
