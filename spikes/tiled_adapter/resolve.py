"""Take what the store reported and see what a Custody record could hold.

The other half of the spike. It reads nodes.json, drives the real
application over real HTTP in-process with no database, and then asks the
question collect.py cannot: given what the store says, what exactly would
go into a record, and does AROC accept it.

There is no Custody context yet, so nothing here posts a dataset. What it
does instead is assemble the value that slice would be handed and run it
through the real `Identifier`, which already exists and already has the
bounds and refusals a dataset's external reference would inherit. A key
that `Identifier` refuses is a key the model cannot carry, and finding
that out now costs nothing.

Run it with:

    uv run --project apps/keeper python spikes/tiled_adapter/resolve.py

Unlike collect.py this half needs `apps/keeper` and must not have the store's
client in the same environment; the two pull incompatible HTTP libraries.
That is why the spike is two scripts and one JSON file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import (
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
    InvalidIdentifierError,
)

HERE = Path(__file__).parent
CAPTURED = HERE.parents[1] / "apps" / "reporter" / "tests" / "nodes.json"
"""The seam between the two halves, written by collect.py.

It sits under the reporter's tests rather than beside this script because
the dataset leg asserts against it there. This half only reads it.
"""

RUN_REF_SCHEME = "bluesky-run-uid"
"""What the reporter already calls the engine's identifier vocabulary.

Not invented here: it is `external_ref_scheme` in the reporter's own
configuration, and this script has to use the same string or the lookup
it is demonstrating would find nothing.
"""

DATASET_REF_SCHEME = "tiled-node-path"
"""The scheme this spike proposes for a Custody record, under test here.

The value it pairs with is the node's path inside the store, which is the
recommendation section 1 of FINDINGS.md argues for. The alternative, the
node's full URI, is built alongside it below so the two can be compared
rather than asserted about.
"""

GRANTS_NEEDED = ("RegisterDataset", "ListRuns", "GetRun")
GRANTS_WITHHELD = ("DefinePlan", "ReportRun", "CompleteRun", "AbortRun", "FailRun")
"""What a dataset reporter may and may not ask for.

The withheld list is the interesting half and it is longer than the
engine reporter's. A thing that hears from the store has no business
saying a run happened or how it ended: it was not there for either. If
one process carries both legs it runs as one actor with the union, and
the split above is then a statement about what a store-only deployment
would grant rather than about today's wiring.
"""


def engine_instant(seconds: float | None) -> str | None:
    """A UNIX timestamp as AROC takes it, or nothing."""
    if not isinstance(seconds, (int, float)):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC).isoformat()


def define_plan(client: TestClient, plan_name: str) -> str:
    """Author a plan out of band, the way an operator would.

    Out of band is the whole point. Section 5 of the sibling spike settled
    that an adapter cannot honestly derive a parameters schema from one
    invocation, so this script does what an operator does and declares a
    schema that constrains nothing.
    """
    response = client.post(
        "/plans",
        json={
            "name": plan_name,
            "parameters_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
        },
    )
    response.raise_for_status()
    return str(response.json()["plan_id"])


def report_run(client: TestClient, plan_id: str, captured: dict[str, Any]) -> str | None:
    """Put the run into AROC, so there is something for a dataset to cite.

    This is the engine reporter's job and it is done here only to make the
    join reachable. A Custody record needs a run id, and a run id comes
    from a run being reported first.
    """
    uid = captured["run_uid"]
    if uid is None:
        return None
    response = client.post(
        "/runs",
        json={
            "plan_id": plan_id,
            "parameters": {},
            "external_ref": {"scheme": RUN_REF_SCHEME, "value": uid},
            "occurred_at": engine_instant(captured["engine_start_time"]),
        },
        headers={"Idempotency-Key": f"report-run:{uid}"},
    )
    if response.status_code != 201:
        return None
    return str(response.json()["run_id"])


def find_run(client: TestClient, uid: str) -> str | None:
    """AROC's id for an engine run, the way a restarted reporter gets it.

    The same call `ArocClient.find_run` already makes. A dataset reporter
    needs it for a different reason: not to recover from a restart, but
    because a Custody record cites a run id and the store only ever says
    a uid.
    """
    response = client.get(
        "/runs",
        params={"external_ref_scheme": RUN_REF_SCHEME, "external_ref_value": uid},
    )
    response.raise_for_status()
    items = response.json()["items"]
    return str(items[0]["run_id"]) if items else None


def as_identifier(scheme: str, value: str) -> tuple[Identifier | None, str]:
    """Build the pair a Custody record would carry, or say why it cannot."""
    try:
        return Identifier(scheme=scheme, value=value), "accepted"
    except InvalidIdentifierError as refusal:
        return None, f"REFUSED: {refusal}"


def main() -> None:
    captured = json.loads(CAPTURED.read_text(encoding="utf-8"))
    scenarios: dict[str, Any] = captured["scenarios"]

    print("== the bound collect.py copied, against the real one ==")
    copied = 200
    print(f"  collect.py says {copied}, aroc.shared.identifier says {IDENTIFIER_VALUE_MAX_LENGTH}")
    print(f"  they agree: {copied == IDENTIFIER_VALUE_MAX_LENGTH}")

    settings = Settings(app_env="test", log_level="WARNING")
    with TestClient(create_app(settings=settings)) as client:
        plan_ids: dict[str, str] = {}
        rows: list[tuple[str, str, str, str]] = []

        for label, scenario in scenarios.items():
            node = scenario.get("node")
            if node is None:
                rows.append((label, "(no node)", "-", "-"))
                continue

            plan_name = "count"
            if plan_name not in plan_ids:
                plan_ids[plan_name] = define_plan(client, plan_name)
            report_run(client, plan_ids[plan_name], scenario)

            uid = scenario["run_uid"]
            run_id = find_run(client, uid)
            reference, verdict = as_identifier(DATASET_REF_SCHEME, node["normalised_path"])
            rows.append(
                (
                    label,
                    (run_id or "NOT FOUND")[:13],
                    verdict,
                    reference.value if reference else "-",
                )
            )

        print("\n== the join, per scenario: engine uid -> AROC run id -> a record ==")
        header = f"{'scenario':<18} {'run id':<15} {'reference':<10} value"
        print(header)
        print("-" * (len(header) + 20))
        for label, run_id, verdict, value in rows:
            print(f"{label:<18} {run_id:<15} {verdict:<10} {value}")

        print("\n== what the record would say, in full, for one run ==")
        sample = scenarios[next(iter(scenarios))]
        node = sample.get("node")
        if node is not None:
            run_id = find_run(client, sample["run_uid"])
            print(f"  run_id        {run_id}")
            print(f"  external_ref  ({DATASET_REF_SCHEME}, {node['normalised_path']})")
            print(f"  occurred_at   {engine_instant(sample['store_stop_time'])}")
            print("                taken from the store's own copy of the ending, not the clock")

        print("\n== the two spellings, run through the real value object ==")
        print("  One node reports two addresses depending on how the handle was got.")
        print("  A reference is a value object, so two spellings are two records.")
        for where, observed in captured["root_addressing"].items():
            print(f"  {where}:")
            for label, field, scheme in (
                ("raw uri", "uri", "tiled-node-uri"),
                ("raw path", "path", DATASET_REF_SCHEME),
                ("normalised path", "normalised_path", DATASET_REF_SCHEME),
            ):
                distinct = {
                    as_identifier(scheme, observed[how][field])[0]
                    for how in ("created", "searched")
                }
                verdict = "one record" if len(distinct) == 1 else f"{len(distinct)} RECORDS"
                print(f"    keyed on {label:<16} {verdict}")

        print("\n== what a record cannot be given ==")
        too_long = "x" * (IDENTIFIER_VALUE_MAX_LENGTH + 1)
        for label, scheme, value in (
            ("a path over the bound", DATASET_REF_SCHEME, too_long),
            ("a node at the store root", DATASET_REF_SCHEME, "/at_the_root"),
            ("nothing at all", DATASET_REF_SCHEME, ""),
        ):
            _, verdict = as_identifier(scheme, value)
            shown = value if len(value) < 30 else f"{len(value)} chars"
            print(f"  {label:<26} {shown:<14} {verdict}")

        print("\n== the slice that takes this ==")
        for method, path in (("POST", "/datasets"), ("GET", "/datasets")):
            response = client.request(method, path, json={} if method == "POST" else None)
            print(f"  {method} {path:<12} -> {response.status_code}")
        print("  Custody exists now, so the POST is a 422 about an empty body")
        print("  rather than a 404 about a route. That is the change this")
        print("  spike was run to inform, arriving back at the spike.")

    print("\n== the grants a dataset reporter needs ==")
    print(f"  grant:    {', '.join(GRANTS_NEEDED)}")
    print(f"  withhold: {', '.join(GRANTS_WITHHELD)}")


if __name__ == "__main__":
    main()
