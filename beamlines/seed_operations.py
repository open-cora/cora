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
so, nothing refuses a second definition of one name, and the record
already holds two operations called `tomo_scan` because of it.

So the resolve below is a check and not a lock, in the same way and for
the same reason as `seed_devices.py`. What closes the gap is a person
reading `--dry-run` output.

## Why a second operation of one name is refused rather than skipped

A procedure references an operation by id. Two operations sharing a name
means a descriptor naming it cannot say which identity it meant, and this
script would have to pick. Picking silently is how a procedure ends up
bound to an operation nobody chose, so this stops and says so.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import DescriptorError, OperationRegister, load_operations

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call may take before it counts as not arriving."""

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


def define(client: httpx.Client, name: str) -> UUID:
    """Create the operation, and return the id the keeper minted for it."""
    response = client.post(
        "/operations",
        json={"name": name},
        headers={"Idempotency-Key": idempotency_key(name)},
    )
    response.raise_for_status()
    return UUID(response.json()["operation_id"])


def seed(client: httpx.Client, register: OperationRegister, *, dry_run: bool) -> int:
    """Walk the register, reporting each row, and return an exit status."""
    added = skipped = duplicated = 0

    for entry in register.operations:
        existing = resolve(client, entry.name)
        if len(existing) > 1:
            duplicated += 1
            print(f"  {entry.name}: {len(existing)} operations already share this name")
            continue
        if existing:
            skipped += 1
            print(f"  {entry.name}: already defined as {existing[0]['operation_id']}")
            continue
        if dry_run:
            added += 1
            print(f"  {entry.name}: would define")
            continue

        operation_id = define(client, entry.name)
        added += 1
        print(f"  {entry.name}: defined as {operation_id}")

    verb = "to define" if dry_run else "defined"
    print(f"\n{added} {verb}, {skipped} already present, {duplicated} ambiguous")

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
