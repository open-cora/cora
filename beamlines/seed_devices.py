"""Register a beamline's devices with a running the keeper.

    uv run --with httpx beamlines/seed_devices.py \
        --descriptor beamlines/2-bm/devices.toml \
        --base-url https://keeper.example \
        --principal-id <uuid> \
        --dry-run

Reads a device register, resolves each reference against `GET /devices`,
and posts the ones that are not there yet. Run it with `--dry-run` first;
registering is an append to a log that nothing takes back.

## This is not idempotent, and cannot be made so from out here

Two separate gaps, and neither is a bug in this script.

Equipment enforces no uniqueness across devices, by design: an
event-sourced aggregate has no consistency boundary spanning its siblings,
so a second registration of one address makes a second record and nothing
notices. The resolve below is therefore a check and not a lock. Two
operators seeding at once, or one seeding while an adapter registers, both
get through.

`Idempotency-Key` narrows the window and does not close it. The key sent
per device is derived from its scheme and reference, so a retry inside the
window returns the same device rather than a second one; but the store
expires a key after `IDEMPOTENCY_TTL_HOURS` (24 by default), and the claim
is scoped to the calling principal, so the same file seeded tomorrow, or
today by somebody else, is not protected by it.

What closes the gap is a person looking at `--dry-run` output.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import DescriptorError, DeviceEntry, DeviceRegister, load

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long one call may take before it counts as not arriving."""

_KEY_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/open-cora/keeper/beamlines/seed_devices")
"""Namespace for the per-device idempotency key.

Derived from the scheme and the reference rather than minted per run, so a
retry of an interrupted seeding asks for the device it already asked for.
Read the module docstring before relying on that for anything wider.
"""


def idempotency_key(scheme: str, ref: str) -> str:
    """The key this script sends for one device, stable across runs."""
    return str(uuid5(_KEY_NAMESPACE, f"{scheme}\n{ref}"))


def _headers(principal_id: UUID, token: str | None) -> dict[str, str]:
    headers = {"X-Principal-Id": str(principal_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve(client: httpx.Client, scheme: str, ref: str) -> list[dict[str, object]]:
    """Every device already registered at this address.

    A list rather than one device or none, because more than one is a
    state this system permits and the listing is where it becomes visible.
    A caller that got handed one at random would not know.
    """
    response = client.get(
        "/devices",
        params={"external_ref_scheme": scheme, "external_ref_value": ref},
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    return list(items)


def register(client: httpx.Client, scheme: str, entry: DeviceEntry) -> UUID:
    """Create the record, and return the id the keeper minted for it."""
    response = client.post(
        "/devices",
        json={
            "external_ref": {"scheme": scheme, "value": entry.ref},
            "name": entry.name,
        },
        headers={"Idempotency-Key": idempotency_key(scheme, entry.ref)},
    )
    response.raise_for_status()
    return UUID(response.json()["device_id"])


def seed(client: httpx.Client, register_file: DeviceRegister, *, dry_run: bool) -> int:
    """Walk the register, reporting each row, and return an exit status.

    Every row is reported, including the ones already there, because the
    question an operator has before running this for real is which rows it
    is about to add.
    """
    scheme = register_file.scheme
    added = skipped = duplicated = 0

    for entry in register_file.devices:
        existing = resolve(client, scheme, entry.ref)
        mark = "" if entry.confirmed else "  (unconfirmed)"

        if len(existing) > 1:
            duplicated += 1
            print(f"  {entry.ref}: {len(existing)} records already registered at this address")
            continue
        if existing:
            skipped += 1
            print(f"  {entry.ref}: already registered as {existing[0]['device_id']}")
            continue
        if dry_run:
            added += 1
            print(f"  {entry.ref}: would register as {entry.name!r}{mark}")
            continue

        device_id = register(client, scheme, entry)
        added += 1
        print(f"  {entry.ref}: registered as {device_id}{mark}")

    verb = "to add" if dry_run else "added"
    print(f"\n{added} {verb}, {skipped} already present, {duplicated} ambiguous")

    if duplicated:
        print(
            "\nAn address with more than one record has to be settled by a person: "
            "nothing here can tell which one an adapter should write to.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token, when the deployment requires an authenticated principal.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        register_file = load(args.descriptor)
    except DescriptorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not register_file.devices:
        print(f"{args.descriptor} carries no devices; nothing to do")
        return 0

    print(
        f"{len(register_file.devices)} device(s) in {args.descriptor}, "
        f"scheme {register_file.scheme!r}" + (", dry run" if args.dry_run else "")
    )

    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=_headers(args.principal_id, args.token),
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        try:
            return seed(client, register_file, dry_run=args.dry_run)
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
