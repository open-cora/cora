"""Which of the four candidate keys could a Custody record actually carry?

The half of the spike that needs no service. `compare.py` settled that an
adapter can speak the protocol without the vendor package; this asks the
question that decides what such an adapter would write down.

There is no capture to read, which is the difference from
`spikes/tiled_adapter/resolve.py`. The candidates here are constructed
exactly as the facility's own bluesky integration constructs them, read
out of public source rather than observed on a wire, and that is marked
in the output. What the candidates are put through is real: the shipped
`Identifier`, and the shipped Custody slice over real HTTP.

Three tests, and only the third has teeth:

    accepted    does `Identifier` take it
    stable      does deriving it twice give the same answer
    singular    does registering it twice leave one record or two

The third is the one that matters, because a reporter that crashes
between sending a registration and hearing back has to send it again, and
the only thing standing between that and a duplicate record is a key it
can recompute having persisted nothing.

Run it with:

    uv run --project apps/api python spikes/dm_adapter/resolve.py

Needs no database and no network. `APP_ENV=test` boots the application
with in-memory adapters and an authorize that permits the system
principal, which is the same arrangement the store spike's half uses.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable

os.environ.setdefault("APP_ENV", "test")

from fastapi.testclient import TestClient  # noqa: E402

from aroc.api.main import create_app  # noqa: E402
from aroc.shared.identifier import Identifier, InvalidIdentifierError  # noqa: E402

RUN_UID = "1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d"
"""A run uid of the shape an engine mints, used to build every candidate."""

EXPERIMENT = "tomo-2026-1"
"""A data management experiment name, which scopes three of the four."""

EXPERIMENT_ID = 4210
FILE_PATH = "scan_0042.h5"

RUN_REF_SCHEME = "bluesky-run-uid"
"""What the reporter already calls the engine's identifier vocabulary."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One proposed spelling of a Custody record's external reference.

    `derive` is called fresh each time rather than holding a value,
    because the whole question about one of these four is whether calling
    it twice gives the same answer.
    """

    key: str
    scheme: str
    derive: Callable[[], str]
    grain: str
    grain_verdict: str
    source: str


def dataset_name() -> str:
    """The dataset name the facility's integration writes.

    `run_uid8_` followed by the first eight characters of the run uid,
    which is 32 bits of a 122-bit identifier. Read out of public source,
    not observed.
    """
    return f"run_uid8_{RUN_UID[:8]}"


GRAIN_MATCHES = "matches"
GRAIN_FINER = "finer"
GRAIN_COARSER = "coarser"

CANDIDATES = (
    Candidate(
        key="A",
        scheme="dm-experiment-dataset",
        derive=lambda: f"{EXPERIMENT}/{dataset_name()}",
        grain="one dataset record, the service's own unit for what a run left",
        grain_verdict=GRAIN_MATCHES,
        source="public source: the integration writes this pair",
    ),
    Candidate(
        key="B",
        scheme="dm-dataset-id",
        derive=lambda: str(uuid.uuid4()),
        grain="one dataset record",
        grain_verdict=GRAIN_MATCHES,
        source="public source: the client mints this at write time",
    ),
    Candidate(
        key="C",
        scheme="dm-experiment-file",
        derive=lambda: f"{EXPERIMENT}/{FILE_PATH}",
        grain="one file, and a run may leave thousands",
        grain_verdict=GRAIN_FINER,
        source="inferred: the service is file-oriented throughout",
    ),
    Candidate(
        key="D",
        scheme="dm-experiment-id",
        derive=lambda: str(EXPERIMENT_ID),
        grain="a whole experiment, which spans many runs",
        grain_verdict=GRAIN_COARSER,
        source="public source: the experiment record carries it",
    ),
)


def accepted(scheme: str, value: str) -> tuple[bool, str]:
    """Would the shipped value object carry this pair."""
    try:
        Identifier(scheme=scheme, value=value)
    except InvalidIdentifierError as exc:
        return False, str(exc)
    return True, "accepted"


def stable(candidate: Candidate) -> tuple[bool, str, str]:
    """Does deriving it twice, from nothing carried over, agree.

    This is the restart, modelled honestly: a reporter that persisted
    nothing calls the derivation again and compares. Anything minted at
    write time fails here and nothing else can.
    """
    first = candidate.derive()
    second = candidate.derive()
    return first == second, first, second


def define_plan(client: TestClient) -> str:
    response = client.post(
        "/plans",
        json={
            "name": f"tomo_fly_{uuid.uuid4().hex[:8]}",
            "parameters_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
        },
    )
    response.raise_for_status()
    return str(response.json()["plan_id"])


def report_run(client: TestClient, plan_id: str, uid: str) -> str:
    """Put a run in, so a dataset has something to cite."""
    response = client.post(
        "/runs",
        json={
            "plan_id": plan_id,
            "parameters": {},
            "external_ref": {"scheme": RUN_REF_SCHEME, "value": uid},
        },
        headers={"Idempotency-Key": f"report-run:{uid}"},
    )
    response.raise_for_status()
    return str(response.json()["run_id"])


def register(client: TestClient, run_id: str, scheme: str, value: str) -> tuple[int, str]:
    """One registration, keyed the way the reporter keys one.

    The header is `dataset_key_for`'s shape, reproduced rather than
    imported: this script must not put the reporter's package in
    `apps/api`'s environment, which is the same separation the store
    spike's two halves keep.
    """
    response = client.post(
        "/datasets",
        json={"run_id": run_id, "external_ref": {"scheme": scheme, "value": value}},
        headers={"Idempotency-Key": f"register-dataset:{value}"},
    )
    if response.status_code != 201:
        return response.status_code, response.text
    return response.status_code, str(response.json()["dataset_id"])


def singular(client: TestClient, run_id: str, candidate: Candidate) -> tuple[bool, str, str]:
    """Register twice as a crashed and restarted reporter would.

    The second call derives the value again rather than reusing the
    first, because that is what a process holding no state does. A key
    that survives this returns the first record's id; one that does not
    mints a second record for one body of data, and nothing anywhere
    says so.
    """
    _, first = register(client, run_id, candidate.scheme, candidate.derive())
    _, second = register(client, run_id, candidate.scheme, candidate.derive())
    return first == second, first, second


def verdict_for(r: dict[str, Any]) -> str:
    """One line on whether a candidate is still in the running, and why not.

    The grain is kept apart from the three tests because it is a
    different kind of objection. A key that fails a test cannot be used.
    A key at the wrong grain could be used and would mean something other
    than what a Custody record claims to mean.
    """
    if not r["stable"]:
        return "DISQUALIFIED: a restart invents a new one"
    if not r["singular"]:
        return "DISQUALIFIED: two records for one thing"
    if not r["accepted"]:
        return "DISQUALIFIED: the value object refuses it"
    if r["grain_verdict"] == GRAIN_COARSER:
        return "DISQUALIFIED: cannot name what one run left"
    if r["grain_verdict"] == GRAIN_FINER:
        return "viable, at one record per file"
    return "usable"


def render(results: list[dict[str, Any]]) -> None:
    print("\nWhat each candidate is")
    print("=" * 22)
    for r in results:
        print(f"\n  {r['key']}  {r['scheme']}")
        print(f"     value   {r['value']}")
        print(f"     grain   {r['grain']}")
        print(f"     source  {r['source']}")

    print("\n\nThe three tests, and the grain")
    print("=" * 30)
    print(f"\n  {'':3} {'accepted':10} {'stable':10} {'one record':12} {'grain':9} verdict")
    print(f"  {'':3} {'-' * 10} {'-' * 10} {'-' * 12} {'-' * 9} {'-' * 32}")
    for r in results:
        print(
            f"  {r['key']:3} {str(r['accepted']):10} {str(r['stable']):10} "
            f"{str(r['singular']):12} {r['grain_verdict']:9} {verdict_for(r)}"
        )

    print("\n\nWhat the failures look like")
    print("=" * 27)
    if all(r["accepted"] and r["stable"] and r["singular"] for r in results):
        print("\n  Nothing failed a test. The disqualifications above are on grain.")
    for r in results:
        if not r["accepted"]:
            print(f"\n  {r['key']} was refused by the value object:")
            print(f"       {r['accepted_note']}")
        if not r["stable"]:
            print(f"\n  {r['key']} is not stable. Derived twice, from no carried state:")
            print(f"       {r['first_derivation']}")
            print(f"       {r['second_derivation']}")
        if not r["singular"]:
            print(f"\n  {r['key']} left two records for one body of data:")
            print(f"       {r['first_record']}")
            print(f"       {r['second_record']}")


def main() -> int:
    app = create_app()
    with TestClient(app) as client:
        plan_id = define_plan(client)
        run_id = report_run(client, plan_id, RUN_UID)

        results: list[dict[str, Any]] = []
        for candidate in CANDIDATES:
            value = candidate.derive()
            ok, note = accepted(candidate.scheme, value)
            is_stable, first_d, second_d = stable(candidate)
            is_singular, first_r, second_r = singular(client, run_id, candidate)
            results.append(
                {
                    "key": candidate.key,
                    "scheme": candidate.scheme,
                    "value": value,
                    "grain": candidate.grain,
                    "grain_verdict": candidate.grain_verdict,
                    "source": candidate.source,
                    "accepted": ok,
                    "accepted_note": note,
                    "stable": is_stable,
                    "first_derivation": first_d,
                    "second_derivation": second_d,
                    "singular": is_singular,
                    "first_record": first_r,
                    "second_record": second_r,
                }
            )

    render(results)

    usable = [r["key"] for r in results if verdict_for(r) == "usable"]
    viable = [r["key"] for r in results if verdict_for(r).startswith("viable")]
    print("\n\nWhere this leaves question 1")
    print("=" * 28)
    print(f"\n  Usable as written:  {', '.join(usable) if usable else 'nothing'}")
    print(f"  Viable at a cost:   {', '.join(viable) if viable else 'nothing'}")
    print("\n  Every candidate cleared `Identifier`, which refuses only an empty")
    print("  or over-long string, so acceptance separated nothing. The column")
    print("  that did the work is the last one.")
    print("\n  What no test here can reach: whether a name the service issues")
    print("  ever changes afterwards. A reprocessing that supersedes a body of")
    print("  data, or a file that moves between storage tiers, would break a")
    print("  key that passes everything above. That needs a real deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
