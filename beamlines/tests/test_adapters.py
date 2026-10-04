"""The adapter register, and the rules that keep it from becoming a wish list.

Which adapter fills which seam is a per-deployment choice, and until now it
lived only in the configuration files on the hosts, which hold tokens and so
are not in git. Nothing in this tree said what a beamline runs. These
registers say it, in the half of the split that belongs here: authored facts
in git at a slow cadence, what exists and what it is called.

## Why a register and not a table in a page

A hand-kept table of names rots silently, and this tree has the scars: a
docstring that counted five of something against a corpus a week older, and
a rule that enumerated six seams in a module carrying seven. Prose that lists
things is not checked by anything.

So the values here are the adapter module names exactly, and the check below
resolves each one against the app that owns the slot. A rename in
`apps/*/src/*/adapters/` turns into a red test here rather than into a page
that quietly lies.

## The vocabulary, which is three words and not two

```
   a module name   this beamline runs that adapter
   none            measured, and there is nothing in this slot
   unsurveyed      nobody has asked the beamline
```

The third exists because the register already draws that distinction in
prose: "not surveyed is an honest entry and not a placeholder: it means
nobody has asked the beamline itself." Collapsing it into `none` would turn
an open question into a measured absence, which is the one direction that
cannot be undone by reading.

## What this register is not

It does not say whether a service is running. 2-BM has a reporter that is
installed and disabled, and its `engine_feed` still names the adapter it is
configured with, because that is the choice the slot records. What is up
right now is a different kind of fact with its own home in
`docs/beamlines/index.md`, and keeping it out of here is what stops two
places disagreeing about it.
"""

import tomllib
from pathlib import Path

import pytest

BEAMLINES = Path(__file__).parents[1]
TREE = BEAMLINES.parent

EXPECTED_BEAMLINES = ("2-bm", "7-bm", "19-bm", "32-id")
"""Every beamline that must carry a register, pinned rather than discovered.

The same reason `test_descriptor.py` pins its device counts. A check that
walks whatever happens to be on disk passes when a directory is missing,
and a beamline with no register is one nothing here verifies. The first
test turns an unlisted directory into a failure instead of a gap.
"""

SLOTS = {
    ("driving", "scan_engine"): "conductor",
    ("driving", "control_system"): "conductor",
    ("recording", "engine_feed"): "reporter",
    ("recording", "store"): "reporter",
    ("recording", "data_format"): "reporter",
    ("processing", "recon_engine"): None,
    ("processing", "data_transfer"): None,
}
"""Every slot, and the app whose adapters may fill it.

`None` means no seam exists for it anywhere in this tree yet. Those slots
are here because a column of `none` across four beamlines is worth reading:
it says nobody has this, which is the question the register exists to
answer. They are safe to carry precisely because the check below refuses
any value but `none` or `unsurveyed` in them, so a placeholder cannot
quietly become a claim about software that was never written.
"""

ABSENT = ("none", "unsurveyed")


def _register(beamline: str) -> dict[str, dict[str, str]]:
    path = BEAMLINES / beamline / "adapters.toml"
    assert path.is_file(), f"{beamline} carries no adapters.toml"
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _adapters(app: str) -> set[str]:
    folder = TREE / "apps" / app / "src" / app / "adapters"
    return {path.stem for path in folder.glob("*.py") if path.stem != "__init__"}


def test_every_beamline_directory_has_a_register_and_is_listed_here() -> None:
    found = {path.name for path in BEAMLINES.iterdir() if (path / "devices.toml").is_file()}
    assert found == set(EXPECTED_BEAMLINES), (
        f"beamline directories {sorted(found)} do not match the pinned list "
        f"{sorted(EXPECTED_BEAMLINES)}, so one of them is checked by nothing"
    )


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_a_register_carries_every_slot_and_invents_none(beamline: str) -> None:
    register = _register(beamline)
    present = {(section, key) for section, body in register.items() for key in body}
    assert present == set(SLOTS), (
        f"{beamline} declares {sorted(present)}, and the slots are {sorted(SLOTS)}. "
        "A slot is added to every beamline or to none, so that the registers can be "
        "read beside each other"
    )


@pytest.mark.parametrize("beamline", EXPECTED_BEAMLINES)
def test_every_named_adapter_resolves_to_one_that_exists(beamline: str) -> None:
    register = _register(beamline)
    for (section, key), app in SLOTS.items():
        value = register[section][key]
        if value in ABSENT:
            continue
        assert app is not None, (
            f"{beamline} {section}.{key} names {value!r}, and no seam for that slot "
            "exists in any app yet. Build the seam before filling the slot"
        )
        assert value in _adapters(app), (
            f"{beamline} {section}.{key} names {value!r}, which is not a module under "
            f"apps/{app}/src/{app}/adapters/. Either the adapter was renamed and this "
            f"register was not, or the value is a wish"
        )


def test_the_slots_with_no_seam_are_empty_at_every_beamline() -> None:
    unbuilt = [slot for slot, app in SLOTS.items() if app is None]
    assert unbuilt, "this rule ranges over nothing, so it proves nothing"
    for beamline in EXPECTED_BEAMLINES:
        register = _register(beamline)
        for section, key in unbuilt:
            assert register[section][key] in ABSENT, (
                f"{beamline} {section}.{key} is filled, so the seam it names now exists "
                f"and {key} should move out of the unbuilt half of SLOTS"
            )
