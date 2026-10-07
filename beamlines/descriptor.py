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
import it. The four projects in this tree share no package on purpose,
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

    `group` is which functional cluster the device belongs to, and it is
    absent for the many records that belong to none. A motor whose only
    description is the channel it occupies in a crate is not part of
    anything anybody has named, and a value there would be invented.
    """

    ref: str
    name: str
    confirmed: bool
    group: str | None = None


@dataclass(frozen=True)
class DeviceRegister:
    """A beamline's devices, the vocabulary they are addressed in, and where.

    `beamline` repeats the directory name on purpose. `README.md` warns
    that a beamline's name is load-bearing in three places that never
    compare themselves to each other, and that a mismatch is silent at
    every one. Writing it here lets one test compare two of them, and
    lets the seeder hand the keeper a beamline without the file's path
    having to be part of its meaning.
    """

    scheme: str
    beamline: str
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

    beamline = settings.get("beamline")
    if not isinstance(beamline, str) or not beamline.strip():
        raise DescriptorError(
            f"{source}: beamline is required and must be a non-empty string. "
            "It is the name the keeper stores and compares as written, and the "
            "name of the directory this file sits in"
        )

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

    return DeviceRegister(scheme=scheme.strip(), beamline=beamline.strip(), devices=tuple(devices))


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

    unknown = set(fields) - {"ref", "name", "confirmed", "group"}
    if unknown:
        raise DescriptorError(
            f"{source}: device {position} ({ref}) carries {sorted(unknown)}, which no keeper "
            "command accepts. See the one rule in beamlines/README.md"
        )

    group = fields.get("group")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise DescriptorError(
            f"{source}: device {position} ({ref}) has a group that is not a non-empty "
            "string. Leave it out to say the device belongs to no cluster; a blank one "
            "is a caller who meant something and did not say it"
        )

    return DeviceEntry(
        ref=ref,
        name=name.strip(),
        confirmed=confirmed,
        group=group.strip() if group is not None else None,
    )


@dataclass(frozen=True)
class OperationEntry:
    """One routine an engine already has, and the shape of its parameters.

    `parameters_schema` is required with no default, the way the keeper
    requires it: an operation whose parameters nobody has described is
    the state that aggregate exists to refuse. It is enforced rather than
    recorded, because defining a procedure validates every run step's
    parameters against the schema of the operation that step names.
    """

    name: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class OperationRegister:
    """The facility's operations.

    No beamline. An operation is one value for the whole facility, which
    is why this register sits beside `facility.toml` rather than in the
    four beamline directories.
    """

    operations: tuple[OperationEntry, ...]


@dataclass(frozen=True)
class RunStep:
    """Ask an engine for a routine, over records the author names.

    `scopes` is required and must name something. Nothing here can look
    inside a routine to work out what it will drive, so a step declaring
    nothing would be one this system believes touches nothing.

    `operation` is a name rather than an identifier. A descriptor is read
    by people and an identifier is minted by the keeper, so the seeder
    resolves one to the other the way it resolves a device reference.
    """

    operation: str
    scopes: tuple[str, ...]
    parameters: dict[str, Any]


@dataclass(frozen=True)
class SetStep:
    """Send one record to one value.

    No scopes. What a set touches is the record it names.
    """

    record: str
    to: float


ProcedureStep = RunStep | SetStep


@dataclass(frozen=True)
class ProcedureEntry:
    """One routine composed over a beamline's records.

    `confirmed` does not mean here what it means on a device. There it
    records how a row was checked and an unconfirmed row is registered
    anyway. Here it is a gate: an unconfirmed procedure is never seeded,
    so the keeper never holds it and nothing can dispatch it.

    The difference is that a procedure is dispatchable and a device is
    not, and that nothing retires a procedure once defined.
    """

    name: str
    confirmed: bool
    steps: tuple[ProcedureStep, ...]


@dataclass(frozen=True)
class ProcedureRegister:
    """A beamline's routines, and the beamline they are dispatched to."""

    beamline: str
    procedures: tuple[ProcedureEntry, ...]


def load_operations(path: Path) -> OperationRegister:
    """Read the operation register, or say exactly what is wrong with it."""
    return operations_from_mapping(_parsed(path), source=str(path))


def load_procedures(path: Path) -> ProcedureRegister:
    """Read a beamline's procedure register, or say what is wrong with it."""
    return procedures_from_mapping(_parsed(path), source=str(path))


def _parsed(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DescriptorError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise DescriptorError(f"{path} is not valid TOML: {exc}") from exc


def operations_from_mapping(settings: Any, *, source: str = "descriptor") -> OperationRegister:
    """Build an operation register from an already-parsed mapping."""
    rows = settings.get("operation", [])
    if not isinstance(rows, list):
        raise DescriptorError(f"{source}: operation must be a list of tables")

    seen: dict[str, int] = {}
    operations: list[OperationEntry] = []
    for position, row in enumerate(cast("list[object]", rows), start=1):
        if not isinstance(row, dict):
            raise DescriptorError(f"{source}: operation {position} must be a table")
        table = cast("dict[str, Any]", row)
        name = table.get("name")
        if not isinstance(name, str) or not name.strip():
            raise DescriptorError(
                f"{source}: operation {position} needs a name, as a non-empty string"
            )
        if name != name.strip() or any(character.isspace() for character in name):
            raise DescriptorError(
                f"{source}: operation {position} is named {name!r}, which holds whitespace. "
                "An operation name is matched rather than read: it has to equal the entry "
                "in run.routines in each conductor's own configuration, hand-edited on "
                "every beamline host, and a mismatch refuses every dispatch there"
            )
        if name in seen:
            raise DescriptorError(
                f"{source}: operation {position} repeats the name {name!r}, "
                f"already used by operation {seen[name]}"
            )

        schema = table.get("parameters_schema")
        if not isinstance(schema, dict) or not schema:
            raise DescriptorError(
                f"{source}: operation {position} needs a non-empty parameters_schema. "
                "The keeper requires one with no default, because an operation whose "
                "parameters nobody has described is what it exists to refuse, and a "
                "procedure's run steps are validated against it"
            )

        seen[name] = position
        operations.append(
            OperationEntry(name=name, parameters_schema=cast("dict[str, Any]", schema))
        )

    return OperationRegister(operations=tuple(operations))


def procedures_from_mapping(settings: Any, *, source: str = "descriptor") -> ProcedureRegister:
    """Build a procedure register from an already-parsed mapping."""
    beamline = settings.get("beamline")
    if not isinstance(beamline, str) or not beamline.strip():
        raise DescriptorError(
            f"{source}: beamline is required and must be a non-empty string. "
            "It is what the keeper routes a dispatch by, and the name of the "
            "directory this file sits in"
        )

    rows = settings.get("procedure", [])
    if not isinstance(rows, list):
        raise DescriptorError(f"{source}: procedure must be a list of tables")

    confirmed_names: dict[str, int] = {}
    procedures: list[ProcedureEntry] = []
    for position, row in enumerate(cast("list[object]", rows), start=1):
        entry = _procedure(row, position, source)
        if entry.confirmed:
            if entry.name in confirmed_names:
                raise DescriptorError(
                    f"{source}: procedure {position} is a second confirmed "
                    f"{entry.name!r}, already confirmed at procedure "
                    f"{confirmed_names[entry.name]}. Nothing retires a procedure, so "
                    "seeding two of one name leaves the record holding both forever"
                )
            confirmed_names[entry.name] = position
        procedures.append(entry)

    return ProcedureRegister(beamline=beamline.strip(), procedures=tuple(procedures))


def _procedure(row: object, position: int, source: str) -> ProcedureEntry:
    if not isinstance(row, dict):
        raise DescriptorError(f"{source}: procedure {position} must be a table")
    table = cast("dict[str, Any]", row)

    name = table.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DescriptorError(f"{source}: procedure {position} needs a name, as a non-empty string")

    confirmed = table.get("confirmed")
    if not isinstance(confirmed, bool):
        raise DescriptorError(
            f"{source}: procedure {position} needs confirmed, as true or false. "
            "It is not defaulted, because it decides whether the routine is seeded "
            "at all and an omission would be read as permission"
        )

    steps = table.get("step", [])
    if not isinstance(steps, list) or not steps:
        raise DescriptorError(
            f"{source}: procedure {position} needs at least one step, as a list of tables"
        )

    composed = [
        _step(step, position, index, source)
        for index, step in enumerate(cast("list[object]", steps), start=1)
    ]
    return ProcedureEntry(name=name.strip(), confirmed=confirmed, steps=tuple(composed))


def _step(row: object, procedure: int, position: int, source: str) -> ProcedureStep:
    where = f"{source}: procedure {procedure} step {position}"
    if not isinstance(row, dict):
        raise DescriptorError(f"{where} must be a table")
    table = cast("dict[str, Any]", row)

    kind = table.get("kind")
    if kind == "run":
        return _run_step(table, where)
    if kind == "set":
        return _set_step(table, where)
    raise DescriptorError(f"{where} has kind {kind!r}, and the kinds are 'run' and 'set'")


def _run_step(table: dict[str, Any], where: str) -> RunStep:
    operation = table.get("operation")
    if not isinstance(operation, str) or not operation.strip():
        raise DescriptorError(
            f"{where} needs an operation, as a name from beamlines/operations.toml"
        )

    scopes = table.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise DescriptorError(
            f"{where} needs scopes, naming at least one record or namespace it drives. "
            "Nothing here can look inside a routine, so a run that declared nothing "
            "would be one this system believes touches nothing"
        )
    named = cast("list[object]", scopes)
    if not all(isinstance(scope, str) and scope.strip() for scope in named):
        raise DescriptorError(f"{where} has a scope that is not a non-empty string: {scopes!r}")

    parameters = table.get("parameters", {})
    if not isinstance(parameters, dict):
        raise DescriptorError(f"{where} has parameters that are not a table")

    return RunStep(
        operation=operation.strip(),
        scopes=tuple(cast("list[str]", named)),
        parameters=cast("dict[str, Any]", parameters),
    )


def _set_step(table: dict[str, Any], where: str) -> SetStep:
    record = table.get("record")
    if not isinstance(record, str) or not record.strip():
        raise DescriptorError(f"{where} needs a record, as a non-empty string")

    to = table.get("to")
    if isinstance(to, bool) or not isinstance(to, (int, float)):
        raise DescriptorError(f"{where} needs a value to set, as a number")

    return SetStep(record=normalize_reference(record), to=float(to))


__all__ = [
    "DescriptorError",
    "DeviceEntry",
    "DeviceRegister",
    "OperationEntry",
    "OperationRegister",
    "ProcedureEntry",
    "ProcedureRegister",
    "ProcedureStep",
    "RunStep",
    "SetStep",
    "from_mapping",
    "load",
    "load_operations",
    "load_procedures",
    "normalize_reference",
    "operations_from_mapping",
    "procedures_from_mapping",
]
