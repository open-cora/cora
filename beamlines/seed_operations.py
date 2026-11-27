"""Define the facility's operations against a running keeper.

    uv run --with httpx beamlines/seed_operations.py \
        --descriptor beamlines/operations.toml \
        --base-url https://keeper.example:8443 \
        --principal-id <uuid> \
        --dry-run

Reads the operation register, resolves each name against `GET /operations`,
and defines the ones that are not there yet. Run it with `--dry-run` first;
defining is an append to a log that nothing takes back.

## Resolution is exact here, and that is the only easy part

`GET /operations` filters by name, so finding out whether one exists is a
single request rather than a walk. What it cannot do is make the answer
stable. A name is deliberately not unique: the endpoint's own page says
so, and nothing refuses a second definition of one name, so a second one
is a single seeding run away.

So the resolve below is a check and not a lock, in the same way and for
the same reason as `seed_devices.py`. What closes the gap is a person
reading `--dry-run` output.

## Why a second operation of one name is refused rather than skipped

A procedure references an operation by id. Two operations sharing a name
means a descriptor naming it cannot say which identity it meant, and this
script would have to pick. Picking silently is how a procedure ends up
bound to an operation nobody chose, so this stops and says so.

## Device use, declared once and by the administrator

Each operation in the register says whether its runs drive equipment, and
this declares that in the keeper for any operation that has not said yet.
A declaration cannot change afterwards, so one that disagrees with the
register is reported rather than written over: settling it means a new
operation, as a changed schema does.

Defining is a beamline account's and declaring is the administrator's, so
a facility runs this twice: once with a beamline's token, which defines
and has its declarations refused, and once with the administrator's, which
finds every operation defined and declares.

## Place use, declared the same way

Each operation also says which of a run's parameters name a place and
which name where it processes, and this declares both lists for any
operation that has not said yet, beside its device use and on the same
terms: once, by the administrator, reported rather than written over when
the keeper holds something else.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import DescriptorError, OperationEntry, OperationRegister, load_operations

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call may take before it counts as not arriving."""

FORBIDDEN = 403
"""The status a keeper answers a caller whose policy does not grant the command."""

_KEY_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://github.com/open-cora/keeper/beamlines/seed_operations"
)
"""Namespace for the per-operation idempotency key.

Derived from the name rather than minted per run, so a retry of an
interrupted seeding asks for the operation it already asked for. Read
`seed_devices.py` before relying on that for anything wider: the store
expires a key, and the claim is scoped to the calling principal.
"""


def idempotency_key(name: str) -> str:
    """The key this script sends for one operation, stable across runs."""
    return str(uuid5(_KEY_NAMESPACE, name))


def _headers(principal_id: UUID, token: str | None) -> dict[str, str]:
    headers = {"X-Principal-Id": str(principal_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve(client: httpx.Client, name: str) -> list[dict[str, object]]:
    """Every operation already defined under this name."""
    response = client.get("/operations", params={"name": name})
    response.raise_for_status()
    return list(response.json().get("items", []))


def define(client: httpx.Client, entry: OperationEntry) -> UUID:
    """Create the operation, and return the id the keeper minted for it."""
    response = client.post(
        "/operations",
        json={"name": entry.name, "parameters_schema": entry.parameters_schema},
        headers={"Idempotency-Key": idempotency_key(entry.name)},
    )
    response.raise_for_status()
    return UUID(response.json()["operation_id"])


def declare(client: httpx.Client, operation_id: str, drives_devices: bool) -> bool:
    """Declare an operation's device use, or say the keeper refused this caller.

    False on a 403, which is a beamline's token asking for what only the
    administrator may do; any other refusal raises.
    """
    response = client.post(
        f"/operations/{operation_id}/device-use", json={"drives_devices": drives_devices}
    )
    if response.status_code == FORBIDDEN:
        return False
    response.raise_for_status()
    return True


def declare_places(client: httpx.Client, operation_id: str, entry: OperationEntry) -> bool:
    """Declare an operation's place use, or say the keeper refused this caller.

    False on a 403, as for device use; any other refusal raises.
    """
    response = client.post(
        f"/operations/{operation_id}/place-use",
        json={
            "place_parameters": list(entry.place_parameters),
            "compute_place_parameters": list(entry.compute_place_parameters),
        },
    )
    if response.status_code == FORBIDDEN:
        return False
    response.raise_for_status()
    return True


def held_place_use(row: dict[str, object]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The place use a listing row holds, or None while nobody has declared it."""
    places = row.get("place_parameters")
    compute = row.get("compute_place_parameters")
    if not isinstance(places, list) or not isinstance(compute, list):
        return None
    return (
        tuple(str(name) for name in cast("list[object]", places)),
        tuple(str(name) for name in cast("list[object]", compute)),
    )


def place_use_said(places: tuple[str, ...], compute: tuple[str, ...]) -> str:
    """A place use as one line of the report."""
    return f"place_parameters = {list(places)}, compute_place_parameters = {list(compute)}"


def seed(client: httpx.Client, register: OperationRegister, *, dry_run: bool) -> int:
    """Walk the register, reporting each row, and return an exit status."""
    added = skipped = duplicated = 0
    declared = unchanged = disagreeing = forbidden = 0

    for entry in register.operations:
        existing = resolve(client, entry.name)
        if len(existing) > 1:
            duplicated += 1
            print(f"  {entry.name}: {len(existing)} operations already share this name")
            continue
        if existing:
            skipped += 1
            operation_id = str(existing[0]["operation_id"])
            held = existing[0].get("drives_devices")
            held_places = held_place_use(existing[0])
            print(f"  {entry.name}: already defined as {operation_id}")
        elif dry_run:
            added += 1
            print(f"  {entry.name}: would define")
            operation_id, held, held_places = "", None, None
        else:
            operation_id, held, held_places = str(define(client, entry)), None, None
            added += 1
            print(f"  {entry.name}: defined as {operation_id}")

        said = f"drives_devices = {str(entry.drives_devices).lower()}"
        if held is None:
            if dry_run:
                declared += 1
                print(f"  {entry.name}: would declare {said}")
            elif declare(client, operation_id, entry.drives_devices):
                declared += 1
                print(f"  {entry.name}: declared {said}")
            else:
                forbidden += 1
                print(f"  {entry.name}: {said} not declared; that is the administrator's")
        elif held == entry.drives_devices:
            unchanged += 1
        else:
            disagreeing += 1
            print(
                f"  {entry.name}: the keeper holds drives_devices = {str(held).lower()} and "
                f"the register says {str(entry.drives_devices).lower()}"
            )

        wanted = (entry.place_parameters, entry.compute_place_parameters)
        said_places = place_use_said(*wanted)
        if held_places is None:
            if dry_run:
                declared += 1
                print(f"  {entry.name}: would declare {said_places}")
            elif declare_places(client, operation_id, entry):
                declared += 1
                print(f"  {entry.name}: declared {said_places}")
            else:
                forbidden += 1
                print(f"  {entry.name}: {said_places} not declared; that is the administrator's")
        elif held_places == wanted:
            unchanged += 1
        else:
            disagreeing += 1
            print(
                f"  {entry.name}: the keeper holds {place_use_said(*held_places)} and the "
                f"register says {said_places}"
            )

    verb = "to define" if dry_run else "defined"
    print(f"\n{added} {verb}, {skipped} already present, {duplicated} ambiguous")
    to_declare = "to declare" if dry_run else "declared"
    print(
        f"{declared} {to_declare}, {unchanged} already declared, {disagreeing} disagreeing, "
        f"{forbidden} left for the administrator"
    )
    if disagreeing:
        print(
            "\nA declaration cannot change. An operation whose device use or place use is "
            "wrong in the keeper needs a new operation, retiring the old one.",
            file=sys.stderr,
        )
        return 1

    if duplicated:
        print(
            "\nA name with more than one operation has to be settled by a person: "
            "a procedure references an operation by id, and nothing here can tell "
            "which identity a descriptor naming it meant.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--ca-cert", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        register = load_operations(args.descriptor)
    except DescriptorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not register.operations:
        print(f"{args.descriptor} carries no operations; nothing to do")
        return 0

    token = args.token
    if args.token_file:
        token = args.token_file.expanduser().read_text(encoding="utf-8").strip()

    print(
        f"{len(register.operations)} operation(s) in {args.descriptor}"
        + (", dry run" if args.dry_run else "")
    )

    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=_headers(args.principal_id, token),
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=str(args.ca_cert.expanduser()) if args.ca_cert else True,
    ) as client:
        try:
            return seed(client, register, dry_run=args.dry_run)
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
