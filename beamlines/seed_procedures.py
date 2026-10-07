"""Define a beamline's confirmed procedures against a running keeper.

    uv run --with httpx beamlines/seed_procedures.py \
        --descriptor beamlines/2-bm/procedures.toml \
        --operations beamlines/operations.toml \
        --base-url https://keeper.example:8443 \
        --principal-id <uuid> \
        --dry-run

Reads a procedure register, resolves each row against `GET /procedures`,
and defines the confirmed ones that are not there yet.

## An unconfirmed row is never sent, and the refusal is here rather than in a habit

`confirmed` is a gate in a procedure register, not the note about
evidence it is in a device register. A drafted routine over a beamline's
real records is dispatchable the instant the keeper holds it, and nothing
retires a procedure once defined.

So this script does not offer a flag to override it. An unconfirmed row
is reported and skipped, on a dry run and on a real one alike, and the
only way to seed one is to confirm it in the file, where the change is
reviewable and attributable.

## Resolution matches on what a routine claims, not only on what it is called

A register holds both states of one routine under one name, differing in
what they drive. Matching on the name alone would read the confirmed
row's presence as the unconfirmed row's and skip a procedure that is not
there, so each candidate's steps are read and its claims compared.

`GET /procedures` filters by name but not by beamline, so the filter
narrows the walk and the beamline is checked here.

## This is not idempotent, for the reasons seed_devices.py gives

Nothing enforces uniqueness across procedures either. The resolve is a
check and not a lock, `Idempotency-Key` narrows the window and does not
close it, and what closes the gap is a person reading `--dry-run` output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import (
    DescriptorError,
    ProcedureEntry,
    ProcedureRegister,
    RunStep,
    load_operations,
    load_procedures,
)

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call may take before it counts as not arriving."""

_KEY_NAMESPACE = uuid5(
    NAMESPACE_URL, "https://github.com/open-cora/keeper/beamlines/seed_procedures"
)
"""Namespace for the per-procedure idempotency key."""


def idempotency_key(beamline: str, procedure: ProcedureEntry) -> str:
    """The key this script sends for one procedure, stable across runs.

    Derived from what the procedure is and does rather than from its name
    alone, so the two rows a register holds under one name do not collide
    on a key the way they would on a title.
    """
    return str(uuid5(_KEY_NAMESPACE, f"{beamline}\n{procedure.name}\n{claims(procedure)}"))


def claims(procedure: ProcedureEntry) -> tuple[str, ...]:
    """The addresses a routine would write to, sorted, from a descriptor row."""
    addresses: list[str] = []
    for step in procedure.steps:
        if isinstance(step, RunStep):
            addresses.extend(step.scopes)
        else:
            addresses.append(step.record)
    return tuple(sorted(addresses))


def held_claims(steps: list[dict[str, Any]]) -> tuple[str, ...]:
    """The same reduction, over what the keeper reports."""
    addresses: list[str] = []
    for step in steps:
        if step.get("kind") == "run":
            addresses.extend(str(scope) for scope in step.get("scopes", []))
        elif step.get("kind") == "set":
            addresses.append(str(step["record"]))
    return tuple(sorted(addresses))


def _headers(principal_id: UUID, token: str | None) -> dict[str, str]:
    headers = {"X-Principal-Id": str(principal_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve(
    client: httpx.Client, beamline: str, procedure: ProcedureEntry
) -> list[dict[str, object]]:
    """Every procedure already defined at this beamline, named this, claiming this."""
    response = client.get("/procedures", params={"name": procedure.name, "limit": 100})
    response.raise_for_status()
    wanted = claims(procedure)

    matched: list[dict[str, object]] = []
    for row in response.json().get("items", []):
        if row["beamline"] != beamline:
            continue
        detail = client.get(f"/procedures/{row['procedure_id']}")
        detail.raise_for_status()
        if held_claims(detail.json().get("steps", [])) == wanted:
            matched.append(row)
    return matched


def body(
    beamline: str, procedure: ProcedureEntry, operations: dict[str, UUID]
) -> dict[str, object]:
    """The request this procedure becomes, with operation names resolved to ids."""
    steps: list[dict[str, object]] = []
    for step in procedure.steps:
        if isinstance(step, RunStep):
            steps.append(
                {
                    "kind": "run",
                    "operation_id": str(operations[step.operation]),
                    "parameters": step.parameters,
                    "scopes": list(step.scopes),
                }
            )
        else:
            steps.append({"kind": "set", "record": step.record, "to": step.to})
    return {"name": procedure.name, "beamline": beamline, "steps": steps}


def define(
    client: httpx.Client, beamline: str, procedure: ProcedureEntry, operations: dict[str, UUID]
) -> UUID:
    """Create the procedure, and return the id the keeper minted for it."""
    response = client.post(
        "/procedures",
        json=body(beamline, procedure, operations),
        headers={"Idempotency-Key": idempotency_key(beamline, procedure)},
    )
    response.raise_for_status()
    return UUID(response.json()["procedure_id"])


def operation_ids(client: httpx.Client, names: set[str]) -> dict[str, UUID]:
    """Resolve every operation a register names, refusing an unusable answer.

    A missing operation and an ambiguous one both stop this before
    anything is written, because a procedure binds to an identity and
    neither case names one.
    """
    resolved: dict[str, UUID] = {}
    for name in sorted(names):
        response = client.get("/operations", params={"name": name})
        response.raise_for_status()
        items = list(response.json().get("items", []))
        if not items:
            raise LookupError(f"no operation named {name!r} is defined; seed operations first")
        if len(items) > 1:
            raise LookupError(
                f"{len(items)} operations are named {name!r}, so a procedure naming it "
                "cannot say which identity it meant"
            )
        resolved[name] = UUID(str(items[0]["operation_id"]))
    return resolved


def seed(
    client: httpx.Client,
    register: ProcedureRegister,
    operations: dict[str, UUID],
    *,
    dry_run: bool,
) -> int:
    """Walk the register, reporting every row including the gated ones."""
    beamline = register.beamline
    added = skipped = gated = duplicated = 0

    for procedure in register.procedures:
        claimed = ", ".join(claims(procedure))
        if not procedure.confirmed:
            gated += 1
            print(f"  {procedure.name!r}: unconfirmed, not seeded. It claims {claimed}")
            continue

        existing = resolve(client, beamline, procedure)
        if len(existing) > 1:
            duplicated += 1
            print(f"  {procedure.name!r}: {len(existing)} procedures already claim {claimed}")
            continue
        if existing:
            skipped += 1
            print(f"  {procedure.name!r}: already defined as {existing[0]['procedure_id']}")
            continue
        if dry_run:
            added += 1
            print(f"  {procedure.name!r}: would define, over {claimed}")
            continue

        procedure_id = define(client, beamline, procedure, operations)
        added += 1
        print(f"  {procedure.name!r}: defined as {procedure_id}, over {claimed}")

    verb = "to define" if dry_run else "defined"
    print(
        f"\n{added} {verb}, {skipped} already present, {gated} unconfirmed and held back, "
        f"{duplicated} ambiguous"
    )

    if duplicated:
        print(
            "\nA routine defined more than once has to be settled by a person: "
            "nothing retires a procedure, so the record holds every copy.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--operations", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--ca-cert", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        register = load_procedures(args.descriptor)
        known = {entry.name for entry in load_operations(args.operations).operations}
    except DescriptorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    named = {
        step.operation
        for procedure in register.procedures
        for step in procedure.steps
        if isinstance(step, RunStep)
    }
    unknown = named - known
    if unknown:
        print(
            f"error: {args.descriptor} runs {sorted(unknown)}, which {args.operations} "
            "does not hold",
            file=sys.stderr,
        )
        return 2

    if not register.procedures:
        print(f"{args.descriptor} carries no procedures; nothing to do")
        return 0

    token = args.token
    if args.token_file:
        token = args.token_file.expanduser().read_text(encoding="utf-8").strip()

    print(
        f"{len(register.procedures)} procedure(s) in {args.descriptor} at "
        f"{register.beamline!r}" + (", dry run" if args.dry_run else "")
    )

    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=_headers(args.principal_id, token),
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=str(args.ca_cert.expanduser()) if args.ca_cert else True,
    ) as client:
        try:
            operations = operation_ids(client, named)
            return seed(client, register, operations, dry_run=args.dry_run)
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
