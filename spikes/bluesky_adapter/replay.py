"""Feed the captured documents into AROC and report what fits.

The other half of the spike. It reads documents.json and drives the real
application over real HTTP, in-process, with no database: `APP_ENV=test`
boots in-memory adapters and `AllowAllAuthorize`, so an unauthenticated
caller runs as the system principal and no headers are needed.

`Adapter` below is shaped the way a real one would be, because the shape
is part of what is being tested. In particular it holds two dictionaries
that a real adapter would also have to hold, and the last section of the
report destroys them to show what that costs.

Run it with:

    uv run --project apps/api python spikes/bluesky_adapter/replay.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings

HERE = Path(__file__).parent
CAPTURED = HERE / "documents.json"

EXTERNAL_REF_SCHEME = "bluesky-run-uid"
"""What this adapter calls Bluesky's own identifier vocabulary.

One of the questions the spike exists to answer is whether this is the
right scheme string and whether the uid alone is the right value. It is
a constant here so the report can point at one place.
"""

INTERRUPTION_DATA_KEY = "interruption"

ENDING_BY_EXIT_STATUS = {
    "success": "complete",
    "abort": "abort",
    "fail": "fail",
}
"""Bluesky's three exit statuses onto AROC's three ending verbs.

Reading this table is the fastest way to see the trap: `RE.stop()` and a
plan that finishes both record `success`, and `RE.halt()` records
`abort`, so the engine method a person called is not recoverable from
here. Three methods collapse into two statuses before AROC ever sees
them.
"""

INTERRUPTION_MOVES = {"pause": "pause", "resume": "resume"}

# Keys this adapter reads off each document. Everything else is reported
# as having nowhere to go, which is the point of tracking the sets at all.
START_KEYS_USED = {"uid", "plan_name", "plan_args"}
STOP_KEYS_USED = {"exit_status", "run_start"}


def _json_type(value: Any) -> str | None:
    """The JSON Schema type keyword for a plain Python value."""
    for python_type, keyword in (
        (bool, "boolean"),
        (int, "integer"),
        (float, "number"),
        (str, "string"),
        (list, "array"),
        (dict, "object"),
    ):
        if isinstance(value, python_type):
            return keyword
    return None


def schema_for(plan_args: dict[str, Any] | None) -> dict[str, Any]:
    """Derive a parameters schema from one run's plan_args.

    Deliberately naive: one property per argument, typed by what the
    value happens to be. A real adapter would want the plan's signature
    rather than one invocation of it, and this is where that difference
    shows up.

    Nothing is said about the contents of an array, because the stored
    subset has no `items` keyword. A detector list can be declared an
    array and no further.
    """
    properties: dict[str, Any] = {}
    for key, value in (plan_args or {}).items():
        keyword = _json_type(value)
        if keyword is not None:
            properties[key] = {"type": keyword}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
    }


class Adapter:
    """A naive document-stream adapter, holding exactly what it must.

    The two dictionaries are the whole of its memory, and neither of them
    is recoverable from AROC: there is no query that answers "which plan
    is named count" and none that answers "which run has uid a3f9". That
    is what the restart section of the report demonstrates.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.plan_ids: dict[str, str] = {}
        self.run_ids: dict[str, str] = {}
        self.refused: list[str] = []
        self.unmapped_start: set[str] = set()
        self.unmapped_stop: set[str] = set()

    def plan_for(self, start: dict[str, Any]) -> str | None:
        """Define a plan for this plan_name, or reuse the one already made."""
        plan_name = str(start.get("plan_name"))
        if plan_name in self.plan_ids:
            return self.plan_ids[plan_name]

        response = self.client.post(
            "/plans",
            json={"name": plan_name, "parameters_schema": schema_for(start.get("plan_args"))},
        )
        if response.status_code != 201:
            self.refused.append(
                f"POST /plans for {plan_name!r}: {response.status_code} {response.text[:120]}"
            )
            return None
        plan_id: str = response.json()["plan_id"]
        self.plan_ids[plan_name] = plan_id
        return plan_id

    def on_start(self, doc: dict[str, Any]) -> None:
        self.unmapped_start |= set(doc) - START_KEYS_USED
        plan_id = self.plan_for(doc)
        if plan_id is None:
            return
        response = self.client.post(
            "/runs",
            json={
                "plan_id": plan_id,
                "parameters": doc.get("plan_args") or {},
                "external_ref": {"scheme": EXTERNAL_REF_SCHEME, "value": doc["uid"]},
            },
        )
        if response.status_code != 201:
            self.refused.append(
                f"POST /runs for uid {doc['uid'][:8]}: "
                f"{response.status_code} {response.text[:120]}"
            )
            return
        self.run_ids[doc["uid"]] = response.json()["run_id"]

    def on_event(self, doc: dict[str, Any], run_uid: str | None) -> None:
        move = INTERRUPTION_MOVES.get(str(doc.get("data", {}).get(INTERRUPTION_DATA_KEY)))
        if move is None or run_uid is None:
            return
        self._transition(run_uid, move)

    def on_stop(self, doc: dict[str, Any]) -> None:
        self.unmapped_stop |= set(doc) - STOP_KEYS_USED
        ending = ENDING_BY_EXIT_STATUS.get(str(doc.get("exit_status")))
        if ending is None:
            self.refused.append(f"no ending verb for exit_status {doc.get('exit_status')!r}")
            return
        self._transition(str(doc.get("run_start")), ending)

    def _transition(self, run_uid: str, verb: str) -> None:
        run_id = self.run_ids.get(run_uid)
        if run_id is None:
            self.refused.append(f"cannot {verb}: no run known for uid {run_uid[:8]}")
            return
        response = self.client.post(f"/runs/{run_id}/{verb}")
        if response.status_code != 204:
            self.refused.append(
                f"POST /runs/../{verb}: {response.status_code} {response.text[:120]}"
            )

    def feed(self, documents: list[dict[str, Any]]) -> str | None:
        """Walk one run's documents in order. Returns the Bluesky uid."""
        run_uid: str | None = None
        for entry in documents:
            name, doc = entry["name"], entry["doc"]
            if name == "start":
                run_uid = doc["uid"]
                self.on_start(doc)
            elif name == "event":
                self.on_event(doc, run_uid)
            elif name == "stop":
                self.on_stop(doc)
        return run_uid

    def status_of(self, run_uid: str) -> str:
        run_id = self.run_ids.get(run_uid)
        if run_id is None:
            return "(no run recorded)"
        response = self.client.get(f"/runs/{run_id}")
        if response.status_code != 200:
            return f"(GET {response.status_code})"
        status: str = response.json()["status"]
        return status


def main() -> None:
    captured = json.loads(CAPTURED.read_text(encoding="utf-8"))

    # WARNING, or the report is buried under a structured log line per call.
    settings = Settings(app_env="test", log_level="WARNING")
    with TestClient(create_app(settings=settings)) as client:
        adapter = Adapter(client)

        rows: list[tuple[str, str, str]] = []
        for name, scenario in captured.items():
            if not scenario["documents"]:
                rows.append((name, scenario["expected_aroc_status"], "(skipped upstream)"))
                continue
            run_uid = adapter.feed(scenario["documents"])
            actual = adapter.status_of(run_uid) if run_uid else "(no start document)"
            rows.append((name, scenario["expected_aroc_status"], actual))

        print(f"{'scenario':<24} {'expected':<12} {'actual':<12} agrees")
        print("-" * 62)
        for name, expected, actual in rows:
            agrees = "yes" if expected == actual else ("n/a" if expected == "unknown" else "NO")
            print(f"{name:<24} {expected:<12} {actual:<12} {agrees}")

        print("\nplans defined, by name:")
        for plan_name, plan_id in adapter.plan_ids.items():
            print(f"  {plan_name:<24} {plan_id}")

        print("\ndocument fields with nowhere to go in AROC:")
        print("  start: " + ", ".join(sorted(adapter.unmapped_start)))
        print("  stop:  " + ", ".join(sorted(adapter.unmapped_stop)))

        print("\nrefusals and failures during the walk:")
        for line in adapter.refused or ["  (none)"]:
            print(f"  {line}" if not line.startswith("  ") else line)

        print("\n--- a redelivered start, demonstrated ---")
        print("An adapter that reconnects and replays will send a start it already sent.")
        before = len(adapter.run_ids)
        first_start = next(
            entry["doc"]
            for entry in captured["completes"]["documents"]
            if entry["name"] == "start"
        )
        known_run_id = adapter.run_ids[first_start["uid"]]
        adapter.on_start(first_start)
        second_run_id = adapter.run_ids[first_start["uid"]]
        duplicate = client.post(
            "/runs",
            json={
                "plan_id": adapter.plan_ids[str(first_start["plan_name"])],
                "parameters": first_start.get("plan_args") or {},
                "external_ref": {
                    "scheme": EXTERNAL_REF_SCHEME,
                    "value": first_start["uid"],
                },
            },
        )
        print(f"  runs known before: {before}, after replaying one start: {len(adapter.run_ids)}")
        print(f"  the adapter's own map overwrote {known_run_id[:8]} with {second_run_id[:8]}")
        print(f"  and AROC accepted a third record of the same engine run: {duplicate.status_code}")
        print(f"  first={known_run_id}\n  second={second_run_id}\n  third={duplicate.json()}")

        print("\n--- the restart, demonstrated ---")
        print("The adapter's uid-to-run map is its only way back to a run.")
        remembered = dict(adapter.run_ids)
        adapter.run_ids.clear()
        adapter.refused.clear()
        stop = next(
            entry["doc"]
            for entry in captured["completes"]["documents"]
            if entry["name"] == "stop"
        )
        adapter.on_stop(stop)
        print(f"After clearing it, replaying one stop document gives: {adapter.refused}")
        print(
            "The run is still there and still readable by its AROC id "
            f"({next(iter(remembered.values()))}), which the adapter no longer has. "
            "Nothing in the API accepts the Bluesky uid."
        )


if __name__ == "__main__":
    main()
