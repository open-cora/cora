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

## A retired row is expected

An operation or a procedure the keeper has retired stays in the record,
readable, and nothing can cite or dispatch it. So a retired row no
register names is not a disagreement: it is how a register drops a row
the record cannot forget. It is asked for explicitly and listed under its
own heading, so a reader can see what the record keeps, and it counts
towards nothing.

What a retired row does not do is stand in for a live one. A register
row whose only copy in the keeper is retired is missing, because nothing
can dispatch it, and a name two rows share counts only the active ones.
A keeper too old to say which rows are retired says nothing, and every
row it lists is read as active, which is what it was.

## A procedure an adoption composed is expected

Adopting a proposal composes a one-step procedure named for the
operation and dispatches it, so every adopted proposal leaves a
procedure that no register names and none should. The procedure says
nothing of where it came from. The proposal does: once adopted, it
names the execution the adoption dispatched, and that execution names
its procedure. So the proposals are walked, each adopted one's
execution is read, and the procedure it names is listed under its own
heading beside the proposal. Like a retired row, it counts towards
nothing.

Only an adopted proposal composed anything. An open one names no
execution yet, and a taken one names a run that something else composed
and dispatched, whose procedure may be one a register holds and is
compared like any other.

The proposal and procedure listings are both summaries the keeper
brings up to date a moment after its log, so a proposal adopted just
before this runs can still read as open while its procedure is already
listed. That run reports the procedure as unexpected; a later one does
not.

## A setup is compared at its latest revision

A setup is revised and never edited, and every revision stays readable, so
the keeper always holds more than a register says. What a register says is
the setup as it should be from now on, which is the latest revision, so that
is the one compared. A register edited after seeding differs until it is
seeded again, and seeding it is what makes a revision.

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
from seed_setups import OPERATIONS_BY_REGISTER, RegisterError, canonical, load_register

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


RETIRED = "Retired"
"""The status the keeper gives a row it no longer offers or hands out."""

ADOPTED = "Adopted"
"""The status of a proposal the keeper chose, then composed and dispatched work for."""


@dataclass
class Gap:
    """What one surface disagrees about, and what it holds that no register needs to name.

    `retired` and `composed` are not disagreements and are not counted in
    `total`: they are the rows the record keeps that no register needs to
    name, the first because nothing can cite or dispatch them and the
    second because an adoption composed them for one run.
    """

    surface: str
    missing: list[str] = field(default_factory=list[str])
    unexpected: list[str] = field(default_factory=list[str])
    differing: list[str] = field(default_factory=list[str])
    retired: list[str] = field(default_factory=list[str])
    composed: list[str] = field(default_factory=list[str])

    @property
    def total(self) -> int:
        return len(self.missing) + len(self.unexpected) + len(self.differing)


def is_retired(row: dict[str, Any]) -> bool:
    """Whether the keeper says this row is retired.

    A row carrying no status came from a keeper that cannot retire
    anything, so it is active.
    """
    return row.get("status") == RETIRED


def beamlines_in(tree: Path) -> list[str]:
    """The beamlines this tree has, which is the directories holding a register."""
    return sorted(path.name for path in tree.iterdir() if (path / "devices.toml").is_file())


def every(
    client: httpx.Client, path: str, *, include_retired: bool = False
) -> list[dict[str, Any]]:
    """Walk a listing to its end, because a first page is not an answer.

    `include_retired` asks for the rows a listing otherwise leaves out.
    The operation and procedure listings take it; a listing that does not
    know it ignores it.
    """
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if include_retired:
            params["include_retired"] = "true"
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
    for row in every(client, "/operations", include_retired=True):
        if is_retired(row):
            gap.retired.append(row["name"])
            continue
        held[row["name"]] = held.get(row["name"], 0) + 1
    gap.retired.sort()

    written = {entry.name for entry in load_operations(tree / "operations.toml").operations}
    for name in sorted(written - held.keys()):
        gap.missing.append(name)
    for name in sorted(held.keys() - written):
        gap.unexpected.append(f"{name} (x{held[name]})" if held[name] > 1 else name)
    for name in sorted(written & held.keys()):
        if held[name] > 1:
            gap.differing.append(
                f"{name}: {held[name]} active operations share this name, so a procedure "
                "referencing it by name cannot say which identity it meant; retire all "
                "but one"
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

    Retired ones are asked for and read like the rest, because a reader of
    the report should see what the record keeps, and marked so the check
    can set them aside.

    The id is kept because it is what an adopted proposal's execution
    names, and the only thing that tells a procedure an adoption composed
    from one composed by hand under the same name.
    """
    detailed: list[dict[str, Any]] = []
    for row in every(client, "/procedures", include_retired=True):
        response = client.get(f"/procedures/{row['procedure_id']}")
        response.raise_for_status()
        body = response.json()
        detailed.append(
            {
                "procedure_id": str(row["procedure_id"]),
                "beamline": row["beamline"],
                "name": row["name"],
                "claims": claimed(body.get("steps", [])),
                "retired": is_retired(row),
            }
        )
    return detailed


def composed_by_adoption(client: httpx.Client) -> dict[str, str]:
    """Each procedure an adoption composed, mapped to the proposal adopted.

    Read from the proposal's side because only that side records it: an
    adopted proposal names the execution its adoption dispatched, and the
    execution names its procedure. The proposal listing carries both the
    status and the execution, so only an adopted proposal costs a second
    read.

    A keeper whose proposals carry no status predates adoption, so none
    of them composed anything.
    """
    composed: dict[str, str] = {}
    for proposal in every(client, "/proposals"):
        if proposal.get("status") != ADOPTED:
            continue
        response = client.get(f"/executions/{proposal['execution_id']}")
        response.raise_for_status()
        composed[str(response.json()["procedure_id"])] = str(proposal["proposal_id"])
    return composed


def check_procedures(client: httpx.Client, tree: Path) -> Gap:
    """Confirmed rows belong in the keeper and unconfirmed ones do not.

    Matched on what a procedure claims as well as on its name, because a
    register holds both states of one routine under one name and they
    differ only in what they drive. Keying on the name alone would make
    the confirmed row's presence look like the unconfirmed row's, which is
    the one reading this check exists to prevent.

    A retired procedure is set aside before any of that. It cannot be
    dispatched, so it satisfies no confirmed row and breaches no gate, and
    it is listed as retired rather than as unexpected.

    A procedure an adoption composed is set aside next, by its id, and
    listed beside the proposal adopted. It was composed for one run rather
    than seeded, so it satisfies no confirmed row and is not an
    unconfirmed one past the gate. Its name is the operation's, which a
    procedure composed by hand can share, so the name decides nothing
    here.
    """
    gap = Gap("procedures")
    held = held_procedures(client)
    composed = composed_by_adoption(client)

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
        if row["retired"]:
            gap.retired.append(f"{row['beamline']} {row['name']!r}")
            continue
        adopted = composed.get(row["procedure_id"])
        if adopted is not None:
            gap.composed.append(f"{row['beamline']} {row['name']!r} from proposal {adopted}")
            continue
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

    gap.retired.sort()
    gap.composed.sort()
    for (beamline, name, claims), count in sorted(expected.items()):
        if count == 0:
            gap.missing.append(f"{beamline} {name!r} over {', '.join(claims)}")
        elif count > 1:
            gap.differing.append(
                f"{beamline} {name!r}: {count} active procedures claim the same thing; "
                "retire all but one"
            )
    return gap


def check_setups(client: httpx.Client, tree: Path) -> Gap:
    """Every setups register, against the latest revision of each setup the keeper holds.

    Keyed by beamline, operation and name, the key the keeper refuses a
    second definition under, and read through the seeder's own loading so
    the two cannot work a register out differently. The listing carries no
    settings, so each setup held under a written name is read for them.
    """
    gap = Gap("setups")
    operations = {
        str(row.get("operation_id")): str(row["name"])
        for row in every(client, "/operations", include_retired=True)
    }
    held: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in every(client, "/setups"):
        operation = operations.get(str(row["operation_id"]), str(row["operation_id"]))
        held.setdefault((row["beamline"], operation, row["name"]), []).append(row)

    written: dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for register in OPERATIONS_BY_REGISTER:
        for path in sorted(tree.glob(f"*/{register}")):
            beamline, operation, setups = load_register(path)
            for name, pair in setups.items():
                written[(beamline, operation, name)] = pair

    for key in sorted(written.keys() - held.keys()):
        gap.missing.append(" ".join(key))
    for key in sorted(held.keys() - written.keys()):
        gap.unexpected.append(" ".join(key))
    for key in sorted(written.keys() & held.keys()):
        rows = held[key]
        if len(rows) > 1:
            gap.differing.append(
                f"{' '.join(key)}: {len(rows)} setups share this name, and a step naming "
                "it is given the one defined first; settle it"
            )
            continue
        settings, schema = written[key]
        response = client.get(f"/setups/{rows[0]['setup_id']}")
        response.raise_for_status()
        latest = response.json()
        held_settings: dict[str, Any] = latest.get("settings") or {}
        changed = sorted(
            name
            for name in set(settings) | set(held_settings)
            if canonical(settings.get(name)) != canonical(held_settings.get(name))
        )
        if changed:
            gap.differing.append(
                f"{' '.join(key)} settings: the register and revision {latest.get('revision')} "
                f"differ in {', '.join(changed)}"
            )
        if canonical(schema) != canonical(latest.get("settings_schema")):
            gap.differing.append(
                f"{' '.join(key)} schema: the register and revision {latest.get('revision')} differ"
            )
    return gap


def report(gap: Gap) -> None:
    if gap.total == 0:
        print(f"{gap.surface}: agrees")
    else:
        print(f"{gap.surface}: {gap.total} disagreement(s)")
    for label, items in (
        ("in a descriptor, not in the keeper", gap.missing),
        ("in the keeper, not in a descriptor", gap.unexpected),
        ("in both, disagreeing", gap.differing),
        ("retired in the keeper, which no descriptor needs to name", gap.retired),
        ("composed by adopting a proposal, which no descriptor needs to name", gap.composed),
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
                check_setups(client, args.tree),
            ]
        except (DescriptorError, RegisterError) as exc:
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
