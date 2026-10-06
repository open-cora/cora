"""The reference rule, and the register that has to keep it."""

from pathlib import Path

import pytest

from descriptor import DescriptorError, from_mapping, load, normalize_reference

BEAMLINES = Path(__file__).parents[1]

PINNED_DEVICE_COUNTS = {
    "2-bm": 3,
    "7-bm": 3,
    "19-bm": 16,
    "32-id": 30,
}
"""Devices each register is expected to carry, by beamline.

Pinned for the reason `test_fitness_scope.py` pins its counts: the check
below that every reference is in normal form ranges over these files, and
with no rows in one of them it passes while verifying nothing. 2-BM was
zero until a sweep filled it, which is what that pin was waiting for. Move
a number deliberately, in the commit that changes the rows.

The table is also what makes discovery safe. A register on disk and absent
from here is a beamline nothing checks, and the first test below turns
that into a failure rather than a gap nobody sees.
"""


PINNED_GROUP_NAMES = {
    "2-bm": {"sample-stack"},
    "7-bm": {"sample-stack"},
    "19-bm": {
        "filters",
        "optics",
        "sample-stack",
        "target",
        "tomo-centering",
        "white-beam-slits",
    },
    "32-id": {
        "beam-position",
        "beamstop",
        "optics",
        "sample-alignment",
        "sample-stack",
        "scintillator",
    },
}
"""The group names each register is allowed to use.

Pinned for a reason the device counts do not cover. A group is a value
rows share rather than a thing anything owns, so `sample_stack` and
`sample-stack` are two groups and nothing downstream notices: the keeper
enforces no vocabulary, and a device that quietly left a group looks
exactly like a device that was never in one.

That is the same gap the loader fills for references, where two
spellings of one motor are two records nothing catches. This file is
the only place either can be caught, so it catches both.
"""


def _registers() -> dict[str, Path]:
    """Every device register in the directory, by beamline.

    Found rather than listed, so adding a beamline does not mean
    remembering to add a constant beside it. What stops discovery from
    quietly covering nothing is the pin table above.
    """
    return {path.parent.name: path for path in sorted(BEAMLINES.glob("*/devices.toml"))}


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
        "beamline": "2-bm",
        "device": [{"ref": "2bmb:m1.RBV", "name": "Sample rotation", "confirmed": True}],
    }
    with pytest.raises(DescriptorError, match="'2bmb:m1'"):
        from_mapping(settings)


def test_from_mapping_refuses_two_rows_at_one_address() -> None:
    settings = {
        "scheme": "epics-record",
        "beamline": "2-bm",
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
        "beamline": "2-bm",
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
        "beamline": "2-bm",
        "device": [{"ref": "2bmb:m1", "name": "Sample rotation"}],
    }
    with pytest.raises(DescriptorError, match="confirmed"):
        from_mapping(settings)


def test_from_mapping_refuses_a_group_that_is_present_and_blank() -> None:
    settings = {
        "scheme": "epics-record",
        "beamline": "2-bm",
        "device": [{"ref": "2bmb:m1", "name": "Sample rotation", "confirmed": True, "group": "  "}],
    }
    with pytest.raises(DescriptorError, match="group"):
        from_mapping(settings)


def test_from_mapping_accepts_a_row_that_belongs_to_no_group() -> None:
    settings = {
        "scheme": "epics-record",
        "beamline": "2-bm",
        "device": [{"ref": "2bmb:m1", "name": "Sample rotation", "confirmed": True}],
    }
    assert from_mapping(settings).devices[0].group is None


def test_from_mapping_refuses_a_register_that_names_no_beamline() -> None:
    settings = {
        "scheme": "epics-record",
        "device": [{"ref": "2bmb:m1", "name": "Sample rotation", "confirmed": True}],
    }
    with pytest.raises(DescriptorError, match="beamline"):
        from_mapping(settings)


def test_from_mapping_accepts_a_well_formed_register() -> None:
    settings = {
        "scheme": "epics-record",
        "beamline": "2-bm",
        "device": [{"ref": "2bmb:m1", "name": "  Sample rotation  ", "confirmed": False}],
    }
    register = from_mapping(settings)
    assert register.scheme == "epics-record"
    assert register.devices[0].name == "Sample rotation"
    assert register.devices[0].confirmed is False


def test_every_register_in_the_directory_is_pinned() -> None:
    assert set(_registers()) == set(PINNED_DEVICE_COUNTS)


@pytest.mark.parametrize("beamline", sorted(PINNED_DEVICE_COUNTS))
def test_every_register_loads_with_its_scheme(beamline: str) -> None:
    assert load(_registers()[beamline]).scheme == "epics-record"


@pytest.mark.parametrize("beamline", sorted(PINNED_DEVICE_COUNTS))
def test_every_register_carries_the_pinned_number_of_devices(beamline: str) -> None:
    assert len(load(_registers()[beamline]).devices) == PINNED_DEVICE_COUNTS[beamline]


@pytest.mark.parametrize("beamline", sorted(PINNED_DEVICE_COUNTS))
def test_every_register_names_the_directory_it_sits_in(beamline: str) -> None:
    """The first check that compares two of the three copies of a name.

    `README.md` says a beamline's name is load-bearing in three places
    that never compare themselves to each other, and that a mismatch is
    silent at all of them: a dispatch to a name nothing asks for waits,
    and a conductor asking for a name nothing dispatches to looks like a
    quiet day. Neither side reports anything, because neither has
    anything to check against. This has something to check against.
    """
    assert load(_registers()[beamline]).beamline == beamline


@pytest.mark.parametrize("beamline", sorted(PINNED_GROUP_NAMES))
def test_every_register_carries_the_pinned_group_names(beamline: str) -> None:
    used = {entry.group for entry in load(_registers()[beamline]).devices if entry.group}
    assert used == PINNED_GROUP_NAMES[beamline]


def test_every_register_with_a_count_also_has_its_groups_pinned() -> None:
    assert set(PINNED_GROUP_NAMES) == set(PINNED_DEVICE_COUNTS)


@pytest.mark.parametrize("beamline", sorted(PINNED_DEVICE_COUNTS))
def test_every_reference_is_already_in_normal_form(beamline: str) -> None:
    for entry in load(_registers()[beamline]).devices:
        assert entry.ref == normalize_reference(entry.ref)
