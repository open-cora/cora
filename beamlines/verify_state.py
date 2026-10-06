"""Compare every descriptor in this directory against a running keeper.

    uv run --with httpx beamlines/verify_state.py \
        --base-url https://keeper.example:8443 \
        --token-file ~/.cora/viewer.token \
        --ca-cert ~/.cora/ca.crt

Read-only. It issues GETs and nothing else, so it is safe against a
deployment in use and needs only a principal that may read.

## Why this exists separately from the seeders

A seeder's `--dry-run` answers one question about one file: what would
this add. This answers the other three, which no seeder can, because each
of them is about what is in the record and not in a file.

    missing       in a descriptor, not in the keeper
    unexpected    in the keeper, not in any descriptor
    differing     in both, disagreeing about a field

The third is the one that cost something. A device's group is fixed when
it is registered and Equipment has no command to change it, so a group
edited in a register after seeding is a disagreement that no dry run
would ever mention and that nothing else here looks for.

## Exit status

Non-zero when any surface shows a gap, so this can be a step in a
deployment rather than only a thing a person reads.

## What it does not check

The agreement between an operation's name and `run.routines` in each
conductor's own configuration. Those files are on the beamline hosts and
this reads the keeper, so the one copy that would catch a mismatch is the
one copy out of reach. `beamlines/operations.toml` says so too.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import (
    DescriptorError,
    ProcedureEntry,
    RunStep,
    load,
    load_operations,
    load_procedures,
)

REQUEST_TIMEOUT_SECONDS = 30.0
"""How long one call may take before it counts as not arriving."""

PAGE_SIZE = 100
"""The largest page the keeper's listings accept."""

SHOWN_PER_CATEGORY = 12
"""How many items of one kind to name before summarising the rest.

A rebuild leaves tens of rows in a category and a reader needs the shape
more than the enumeration. The count above a listing is always the whole
of it, so nothing is hidden by this, only folded.
"""


@dataclass
class Gap:
    """What one surface disagrees about."""

    surface: str
    missing: list[str] = field(default_factory=list[str])
    unexpected: list[str] = field(default_factory=list[str])
    differing: list[str] = field(default_factory=list[str])

    @property
    def total(self) -> int:
        return len(self.missing) + len(self.unexpected) + len(self.differing)


def beamlines_in(tree: Path) -> list[str]:
    """The beamlines this tree has, which is the directories holding a register."""
    return sorted(path.name for path in tree.iterdir() if (path / "devices.toml").is_file())


def every(client: httpx.Client, path: str) -> list[dict[str, Any]]:
    """Walk a listing to its end, because a first page is not an answer."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        response = client.get(path, params=params)
        response.raise_for_status()
        body = response.json()
        items.extend(body.get("items", []))
        cursor = body.get("next_cursor")
        if not cursor:
            return items


def check_devices(client: httpx.Client, tree: Path) -> Gap:
    gap = Gap("devices")
    held = {
        (row["beamline"], row["external_ref"]["value"]): row for row in every(client, "/devices")
    }

    written: set[tuple[str, str]] = set()
    for beamline in beamlines_in(tree):
        for entry in load(tree / beamline / "devices.toml").devices:
            key = (beamline, entry.ref)
            written.add(key)
            row = held.get(key)
            if row is None:
                gap.missing.append(f"{beamline} {entry.ref} ({entry.name})")
                continue
            if row["name"] != entry.name:
                gap.differing.append(
                    f"{beamline} {entry.ref} name: file {entry.name!r}, keeper {row['name']!r}"
                )
            if row.get("group") != entry.group:
                gap.differing.append(
                    f"{beamline} {entry.ref} group: file {entry.group!r}, "
                    f"keeper {row.get('group')!r}"
                )

    for beamline, ref in sorted(held.keys() - written):
        gap.unexpected.append(f"{beamline} {ref} ({held[(beamline, ref)]['name']})")
    return gap


def check_operations(client: httpx.Client, tree: Path) -> Gap:
    gap = Gap("operations")
    held: dict[str, int] = {}
    for row in every(client, "/operations"):
        held[row["name"]] = held.get(row["name"], 0) + 1

    written = {entry.name for entry in load_operations(tree / "operations.toml").operations}
    for name in sorted(written - held.keys()):
        gap.missing.append(name)
    for name in sorted(held.keys() - written):
        gap.unexpected.append(f"{name} (x{held[name]})" if held[name] > 1 else name)
    for name in sorted(written & held.keys()):
        if held[name] > 1:
            gap.differing.append(
                f"{name}: {held[name]} operations share this name, so a procedure "
                "referencing it by name cannot say which identity it meant"
            )
    return gap


def claimed(steps: list[dict[str, Any]]) -> tuple[str, ...]:
    """What a procedure touches, as the keeper reports it.

    A run step declares its scopes and a set step names one record, so
    both sides of the comparison reduce to the same thing: the addresses
    this routine would write to.
    """
    addresses: list[str] = []
    for step in steps:
        if step.get("kind") == "run":
            addresses.extend(str(scope) for scope in step.get("scopes", []))
        elif step.get("kind") == "set":
            addresses.append(str(step["record"]))
    return tuple(sorted(addresses))


def written_claim(procedure: ProcedureEntry) -> tuple[str, ...]:
    """The same reduction, over a descriptor row."""
    addresses: list[str] = []
    for step in procedure.steps:
        if isinstance(step, RunStep):
            addresses.extend(step.scopes)
        else:
            addresses.append(step.record)
    return tuple(sorted(addresses))


def held_procedures(client: httpx.Client) -> list[dict[str, Any]]:
    """Every procedure, with its steps, because a name does not identify one.

    A listing gives names and counts. Two procedures of one name can claim
    entirely different things, and which they claim is the whole of what
    makes one safe and another not, so each is read.
    """
    detailed: list[dict[str, Any]] = []
    for row in every(client, "/procedures"):
        response = client.get(f"/procedures/{row['procedure_id']}")
        response.raise_for_status()
        body = response.json()
        detailed.append(
            {
                "beamline": row["beamline"],
                "name": row["name"],
                "claims": claimed(body.get("steps", [])),
            }
        )
    return detailed


def check_procedures(client: httpx.Client, tree: Path) -> Gap:
    """Confirmed rows belong in the keeper and unconfirmed ones do not.

    Matched on what a procedure claims as well as on its name, because a
    register holds both states of one routine under one name and they
    differ only in what they drive. Keying on the name alone would make
    the confirmed row's presence look like the unconfirmed row's, which is
    the one reading this check exists to prevent.
    """
    gap = Gap("procedures")
    held = held_procedures(client)

    expected: dict[tuple[str, str, tuple[str, ...]], int] = {}
    gated: dict[tuple[str, str, tuple[str, ...]], str] = {}
    for beamline in beamlines_in(tree):
        for procedure in load_procedures(tree / beamline / "procedures.toml").procedures:
            key = (beamline, procedure.name, written_claim(procedure))
            if procedure.confirmed:
                expected[key] = 0
            else:
                gated[key] = ", ".join(written_claim(procedure))

    for row in held:
        key = (row["beamline"], row["name"], row["claims"])
        if key in expected:
            expected[key] += 1
        elif key in gated:
            gap.differing.append(
                f"{row['beamline']} {row['name']!r} is an unconfirmed row and the keeper "
                f"holds it. An unconfirmed procedure is never seeded, and this one "
                f"claims {gated[key]}"
            )
        else:
            claims = ", ".join(row["claims"]) or "nothing"
            gap.unexpected.append(f"{row['beamline']} {row['name']!r} over {claims}")

    for (beamline, name, claims), count in sorted(expected.items()):
        if count == 0:
            gap.missing.append(f"{beamline} {name!r} over {', '.join(claims)}")
        elif count > 1:
            gap.differing.append(
                f"{beamline} {name!r}: {count} procedures claim the same thing, and "
                "nothing retires one"
            )
    return gap


def report(gap: Gap) -> None:
    if gap.total == 0:
        print(f"{gap.surface}: agrees")
        return
    print(f"{gap.surface}: {gap.total} disagreement(s)")
    for label, items in (
        ("in a descriptor, not in the keeper", gap.missing),
        ("in the keeper, not in a descriptor", gap.unexpected),
        ("in both, disagreeing", gap.differing),
    ):
        if not items:
            continue
        print(f"  {label}: {len(items)}")
        for line in items[:SHOWN_PER_CATEGORY]:
            print(f"    {line}")
        if len(items) > SHOWN_PER_CATEGORY:
            print(f"    ... and {len(items) - SHOWN_PER_CATEGORY} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tree", type=Path, default=Path(__file__).parent)
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--ca-cert", type=Path, default=None)
    args = parser.parse_args(argv)

    token = args.token
    if args.token_file:
        token = args.token_file.expanduser().read_text(encoding="utf-8").strip()

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    verify: Any = str(args.ca_cert.expanduser()) if args.ca_cert else True

    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=verify,
    ) as client:
        try:
            gaps = [
                check_devices(client, args.tree),
                check_operations(client, args.tree),
                check_procedures(client, args.tree),
            ]
        except DescriptorError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    for gap in gaps:
        report(gap)

    total = sum(gap.total for gap in gaps)
    print(f"\n{total} disagreement(s) across {len(gaps)} surfaces")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
