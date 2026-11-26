"""Define and revise a beamline's setups against a running keeper.

    uv run --with httpx beamlines/seed_setups.py \
        --register beamlines/19-bm/processing.toml \
        --base-url https://keeper.example:8443 \
        --principal-id <uuid> \
        --dry-run

A setups register holds the named settings one operation runs with at one
beamline. `processing.toml` holds the `process` operation's. Each
`[config.<name>]` table is one setup, and an optional `[bounds.<name>]`
table narrows any of its settings. The beamline is the directory the file
sits in, as it is for every register here.

## The schema is worked out rather than written

The keeper holds a setup's values and the schema they satisfy. Writing the
schema beside the values would be two documents saying one thing, kept in
step by nobody, so this works it out: each setting's type from its value,
and its minimum, maximum, allowed values, pattern and unit from the bounds
table. A bound for a setting the setup does not hold, or one using a
keyword the keeper's schema subset refuses, stops this before anything is
sent.

## Defined, revised, or left alone

A setup the keeper does not hold under this name, for this operation at
this beamline, is defined. One it holds with the same settings and schema
is left alone. One whose settings or schema differ is revised, against the
revision this just read, so a revision somebody else wrote in between is
refused by the keeper rather than written over.

## This is not idempotent, for the reasons seed_devices.py gives

The keeper refuses a second setup under a held name, but that refusal is a
check and not a lock, and the listing it reads is filled by a projection
that can lag the log. `Idempotency-Key` narrows the window on a definition
and does not close it, and what closes the gap is a person reading
`--dry-run` output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).parent))

from seed_procedures import REQUEST_TIMEOUT_SECONDS, operation_ids

OPERATIONS_BY_REGISTER = {"processing.toml": "process"}
"""Which operation each setups register holds settings for, by file name."""

BOUNDS = frozenset({"minimum", "maximum", "enum", "pattern", "unit"})
"""The keywords a bound may use: the keeper's schema subset, less the structural ones.

A tree-tier check compares this with the subset the keeper enforces, so a
keyword the keeper stops accepting stops being offered here.
"""

DRAFT = "https://json-schema.org/draft/2020-12/schema"

_KEY_NAMESPACE = uuid5(NAMESPACE_URL, "https://github.com/open-cora/keeper/beamlines/seed_setups")


class RegisterError(ValueError):
    """A setups register this script will not send."""


def settings_type(name: str, value: object) -> str:
    """The JSON Schema type a setting's value has, refused where it has none here."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise RegisterError(f"{name!r} is {value!r}; a setting is a string, a number or a boolean")


def settings_schema(setup: str, settings: dict[str, Any], bounds: dict[str, Any]) -> dict[str, Any]:
    """The schema a setup's settings satisfy, worked out from them and their bounds."""
    unheld = sorted(set(bounds) - set(settings))
    if unheld:
        raise RegisterError(f"{setup!r} bounds {unheld}, which it holds no value for")
    properties: dict[str, Any] = {}
    for name, value in settings.items():
        described: dict[str, Any] = {"type": settings_type(name, value)}
        bound: dict[str, Any] = bounds.get(name) or {}
        refused = sorted(set(bound) - BOUNDS)
        if refused:
            raise RegisterError(
                f"{setup!r} bounds {name!r} with {refused}; a bound may use {sorted(BOUNDS)}"
            )
        described.update(bound)
        properties[name] = described
    return {"$schema": DRAFT, "type": "object", "properties": properties}


def load_register(path: Path) -> tuple[str, str, dict[str, tuple[dict[str, Any], dict[str, Any]]]]:
    """A register's beamline, its operation, and each setup's settings and schema."""
    operation = OPERATIONS_BY_REGISTER.get(path.name)
    if operation is None:
        raise RegisterError(
            f"{path.name} is not a setups register; the registers are "
            f"{sorted(OPERATIONS_BY_REGISTER)}"
        )
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    tables: dict[str, Any] = document.get("config") or {}
    if not tables:
        raise RegisterError(f"{path} holds no [config.<name>] tables")
    every_bound: dict[str, Any] = document.get("bounds") or {}
    unnamed = sorted(set(every_bound) - set(tables))
    if unnamed:
        raise RegisterError(f"{path} bounds {unnamed}, which it holds no setup for")
    setups = {
        name: (dict(settings), settings_schema(name, dict(settings), every_bound.get(name) or {}))
        for name, settings in tables.items()
    }
    return path.parent.name, operation, setups


def canonical(document: Any) -> str:
    """A document as one string, so two say the same thing exactly when the strings match.

    Keys sorted, and a boolean kept apart from a number, which is the
    reading the keeper compares revisions by.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def idempotency_key(beamline: str, operation: str, name: str, settings: dict[str, Any]) -> str:
    """The key a definition is retried under, changing whenever what it defines does.

    Derived from the content as well as the name, so a retry of an
    interrupted run asks for exactly what it asked for, and an edited
    register is a new request rather than a reused key with a different
    body, which the keeper refuses.
    """
    digest = hashlib.sha256(canonical(settings).encode()).hexdigest()
    return str(uuid5(_KEY_NAMESPACE, f"{beamline}/{operation}/{name}/{digest}"))


def held(
    client: httpx.Client, beamline: str, operation_id: UUID, name: str
) -> list[dict[str, Any]]:
    """The setups the keeper holds under this key, checked locally as well as filtered."""
    response = client.get(
        "/setups",
        params={"beamline": beamline, "operation_id": str(operation_id), "name": name},
    )
    response.raise_for_status()
    return [
        item
        for item in response.json().get("items", [])
        if item.get("beamline") == beamline
        and item.get("name") == name
        and str(item.get("operation_id")) == str(operation_id)
    ]


def seed(
    client: httpx.Client,
    beamline: str,
    operation: str,
    operation_id: UUID,
    setups: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    *,
    dry_run: bool,
) -> int:
    """Define each setup the keeper lacks, revise each that differs, and report every one."""
    defined = revised = same = ambiguous = 0
    for name, (settings, schema) in setups.items():
        found = held(client, beamline, operation_id, name)
        if len(found) > 1:
            ambiguous += 1
            print(f"  {name!r}: {len(found)} setups already hold this name")
            continue
        if not found:
            defined += 1
            if dry_run:
                print(f"  {name!r}: would define, {len(settings)} settings")
                continue
            response = client.post(
                "/setups",
                json={
                    "beamline": beamline,
                    "operation_id": str(operation_id),
                    "name": name,
                    "settings": settings,
                    "settings_schema": schema,
                },
                headers={"Idempotency-Key": idempotency_key(beamline, operation, name, settings)},
            )
            response.raise_for_status()
            print(f"  {name!r}: defined as {response.json()['setup_id']}")
            continue

        setup_id = str(found[0]["setup_id"])
        current = client.get(f"/setups/{setup_id}")
        current.raise_for_status()
        now = current.json()
        if canonical(now["settings"]) == canonical(settings) and canonical(
            now["settings_schema"]
        ) == canonical(schema):
            same += 1
            print(f"  {name!r}: already holds these settings, at revision {now['revision']}")
            continue
        revised += 1
        if dry_run:
            print(f"  {name!r}: would revise revision {now['revision']}")
            continue
        response = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": now["revision"],
                "settings": settings,
                "settings_schema": schema,
            },
        )
        response.raise_for_status()
        print(f"  {name!r}: revised to revision {response.json()['revision']}")

    to_define = "to define" if dry_run else "defined"
    to_revise = "to revise" if dry_run else "revised"
    print(
        f"\n{defined} {to_define}, {revised} {to_revise}, {same} unchanged, {ambiguous} ambiguous"
    )
    if ambiguous:
        print(
            "\nA name held by more than one setup has to be settled by a person: a step "
            "names its setup by name, and the keeper answers with the one defined first.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument("--token", default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--ca-cert", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        beamline, operation, setups = load_register(args.register)
    except (RegisterError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    token = args.token
    if args.token_file:
        token = args.token_file.expanduser().read_text(encoding="utf-8").strip()

    print(
        f"{len(setups)} setup(s) for {operation!r} in {args.register} at {beamline!r}"
        + (", dry run" if args.dry_run else "")
    )

    headers = {"X-Principal-Id": str(args.principal_id)}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(
        base_url=str(args.base_url).rstrip("/"),
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
        verify=str(args.ca_cert.expanduser()) if args.ca_cert else True,
    ) as client:
        try:
            operation_id = operation_ids(client, {operation})[operation]
            return seed(client, beamline, operation, operation_id, setups, dry_run=args.dry_run)
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except httpx.HTTPError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
