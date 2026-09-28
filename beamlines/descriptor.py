"""Reading a beamline's device register, and the one rule on a reference.

Deliberately dependency-free, so a person standing at a beamline can read
a descriptor with the interpreter they already have. TOML for the same
reason `reporter.config` chose it: `tomllib` is in the standard library,
and a table of addresses to labels is obvious in a file.

## Why this refuses rather than normalizes

`normalize_reference` says what normal form is, and `load` rejects any
reference not already in it instead of quietly converting on the way past.

Two reasons, and neither is strictness for its own sake. A reader of the
file has to be able to see what will be registered, and a loader that
silently rewrote `2bmb:m1.RBV` to `2bmb:m1` would make the file and the
register disagree about the beamline. And the refusal is the only place
a duplicate can be caught at all: `apps/keeper/docs/bounded-contexts/equipment.md`
concedes that nothing enforces uniqueness across devices, so two spellings
of one motor are two records that nothing notices, and a caller resolving
a device is about to write to whatever comes back.

The error names the normal form, so the fix is a copy and paste.

## Why the rule is reimplemented here

`conductor.claims.Scope.record` does the same thing, and this does not
import it. The three applications in this tree share no package on purpose,
and `apps/conductor` is not a dependency of a script that talks to an HTTP
API. The cost is one duplicated rule, and `beamlines/tests/` is what
holds the copies to the same table of cases.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

FIELD_SEPARATOR = "."
"""Separates an EPICS record from one of its fields."""

NAMESPACE_SEPARATOR = ":"
"""Separates the segments of an EPICS name."""


class DescriptorError(ValueError):
    """A descriptor cannot be used, with the reason a person can fix.

    Raised at load, for the reason `reporter.config.ConfigError` is: a
    seeder that discovers a malformed reference partway through has
    already registered whatever came before it, and an append-only log
    does not take those back.
    """


def normalize_reference(value: str) -> str:
    """Reduce an address to the record it names.

    Trimmed, cut at the first field separator, and stripped of a trailing
    namespace separator, which is what `conductor.claims.Scope.record`
    produces for the same input. A record covers itself and nothing else,
    so `2bmb:m1` and `2bmb:m10` stay two motors.
    """
    cleaned = value.strip()
    if FIELD_SEPARATOR in cleaned:
        cleaned = cleaned.split(FIELD_SEPARATOR, 1)[0]
    cleaned = cleaned.rstrip(NAMESPACE_SEPARATOR)
    if not cleaned:
        raise DescriptorError(f"A device reference cannot be empty (got: {value!r})")
    return cleaned


@dataclass(frozen=True)
class DeviceEntry:
    """One row of the register: where it is, what to call it, who says so.

    `confirmed` records whether the row was verified against the beamline
    or read off documentation. It is the one field here that describes the
    record rather than the hardware, which is why it survives the rule in
    `README.md` against fields no keeper command accepts.
    """

    ref: str
    name: str
    confirmed: bool


@dataclass(frozen=True)
class DeviceRegister:
    """A beamline's devices, and the vocabulary their addresses belong to."""

    scheme: str
    devices: tuple[DeviceEntry, ...]


def load(path: Path) -> DeviceRegister:
    """Read a device register, or say exactly what is wrong with it."""
    try:
        settings: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DescriptorError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise DescriptorError(f"{path} is not valid TOML: {exc}") from exc

    return from_mapping(settings, source=str(path))


def from_mapping(settings: Any, *, source: str = "descriptor") -> DeviceRegister:
    """Build a register from an already-parsed mapping.

    Separate from `load` so the shape can be checked without a file, which
    is the arrangement `reporter.config` uses for the same reason.
    """
    scheme = settings.get("scheme")
    if not isinstance(scheme, str) or not scheme.strip():
        raise DescriptorError(f"{source}: scheme is required and must be a non-empty string")

    rows = settings.get("device", [])
    if not isinstance(rows, list):
        raise DescriptorError(f"{source}: device must be a list of tables")
    # `isinstance` narrows `Any` to `list[Unknown]`, which leaves every row
    # below unknown to a strict typechecker. The cast says only that the list
    # holds things; what each one is stays `_entry`'s question.
    entries = cast("list[object]", rows)

    seen: dict[str, int] = {}
    devices: list[DeviceEntry] = []
    for position, row in enumerate(entries, start=1):
        entry = _entry(row, position, source)
        if entry.ref in seen:
            raise DescriptorError(
                f"{source}: device {position} repeats the reference {entry.ref!r}, "
                f"already used by device {seen[entry.ref]}"
            )
        seen[entry.ref] = position
        devices.append(entry)

    return DeviceRegister(scheme=scheme.strip(), devices=tuple(devices))


def _entry(row: object, position: int, source: str) -> DeviceEntry:
    if not isinstance(row, dict):
        raise DescriptorError(f"{source}: device {position} must be a table")
    # A TOML table always keys on strings, so this asserts what the parser
    # guarantees rather than what the code hopes. The values stay `object`,
    # because every one of them is checked by name a few lines down.
    fields = cast("dict[str, object]", row)

    ref = fields.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise DescriptorError(f"{source}: device {position} needs a ref, as a non-empty string")

    normal = normalize_reference(ref)
    if ref != normal:
        raise DescriptorError(
            f"{source}: device {position} has the reference {ref!r}, which is not in "
            f"normal form; write it as {normal!r}. A reference is one record: trimmed, "
            f"cut at the first {FIELD_SEPARATOR!r}, with no trailing {NAMESPACE_SEPARATOR!r}"
        )

    name = fields.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DescriptorError(
            f"{source}: device {position} ({ref}) needs a name, as a non-empty string. "
            "It is this system's own label, never the facility's description field"
        )

    confirmed = fields.get("confirmed")
    if not isinstance(confirmed, bool):
        raise DescriptorError(
            f"{source}: device {position} ({ref}) needs confirmed, as true or false. "
            "Whether a row was checked against the beamline is not something to leave unsaid"
        )

    unknown = set(fields) - {"ref", "name", "confirmed"}
    if unknown:
        raise DescriptorError(
            f"{source}: device {position} ({ref}) carries {sorted(unknown)}, which no keeper "
            "command accepts. See the one rule in beamlines/README.md"
        )

    return DeviceEntry(ref=ref, name=name.strip(), confirmed=confirmed)


__all__ = [
    "DescriptorError",
    "DeviceEntry",
    "DeviceRegister",
    "from_mapping",
    "load",
    "normalize_reference",
]
