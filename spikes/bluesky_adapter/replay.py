"""Feed the captured documents into AROC and report what fits.

The other half of the spike. It reads documents.json and drives the real
application over real HTTP, in-process, with no database: `APP_ENV=test`
boots in-memory adapters and `AllowAllAuthorize`, so an unauthenticated
caller runs as the system principal and no headers are needed.

`Adapter` below is shaped the way a real one would be, because the shape
is part of what is being tested. In particular it holds two dictionaries
that a real adapter would also have to hold, and the last section of the
report destroys them to show what that costs.

It used to cost everything. A cleared map meant a run the adapter could
never reach again, and a plan it would define a second time, because
nothing in the API accepted the engine's own vocabulary for either.
`GET /runs` and `GET /plans` now do, so the restart section below shows
both halves recovering. What it cannot show is which of two plans
sharing a name is the current one, because nothing in AROC says.

Run it with:

    uv run --project apps/keeper python spikes/bluesky_adapter/replay.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings

HERE = Path(__file__).parent
CAPTURED = HERE.parents[1] / "apps" / "reporter" / "tests" / "documents.json"
"""The capture, which now lives with the reporter rather than here.

It moved when the reporter's translation core landed and started asserting
against it. This directory is marked for deletion and the reporter is not,
so the fixture had to stop living in the throwaway half.
"""

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
START_KEYS_USED = {"uid", "plan_name", "plan_args", "time"}
STOP_KEYS_USED = {"exit_status", "run_start", "time"}


def engine_time(doc: dict[str, Any]) -> str | None:
    """A Bluesky document's own `time`, as an ISO instant AROC will take.

    Bluesky stamps documents with UNIX seconds. AROC refuses a timestamp
    without an offset, so the conversion names UTC explicitly rather than
    letting the local zone decide.

    This is the field the spike originally reported as having nowhere to
    go, which is what prompted the endpoints to start accepting one.
    """
    seconds = doc.get("time")
    if not isinstance(seconds, (int, float)):
        return None
    return datetime.fromtimestamp(float(seconds), tz=UTC).isoformat()


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


def list_plan_ids(client: TestClient) -> list[str]:
    """Every plan AROC holds, read back through the list endpoint.

    The report uses it to count, so that "a restarted adapter does not
    author a second plan" is shown against AROC's own records rather than
    against the adapter's memory of them, which is the thing being
    cleared.
    """
    response = client.get("/plans", params={"limit": 100})
    items: list[dict[str, Any]] = response.json()["items"]
    return [str(item["plan_id"]) for item in items]


class Adapter:
    """A naive document-stream adapter, holding exactly what it must.

    The two dictionaries are the whole of its memory, and both are now a
    cache rather than the only copy: `GET /runs` answers "which run has
    uid a3f9" and `GET /plans` answers "which plan is named count". That
    is what the restart section of the report demonstrates, and it is
    what makes a reporter something you can kill and start again.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.plan_ids: dict[str, str] = {}
        self.run_ids: dict[str, str] = {}
        self.refused: list[str] = []
        self.unmapped_start: set[str] = set()
        self.unmapped_stop: set[str] = set()

    def plan_id_for(self, plan_name: str) -> str | None:
        """This adapter's id for a plan name, from memory or from AROC.

        The plan half of the restart, and the shape differs from the run
        half in what a second match means. Two runs under one engine uid
        is somebody recording the same run twice, which is a defect. Two
        plans under one name is the aggregate working as designed: one
        routine constrained two ways is two plans.

        So this cannot treat a second row as a warning. It takes the
        newest, which is the order the page arrives in, and that is a
        guess rather than an answer: nothing in AROC says which of two
        plans named `count` an operator means today. Whatever closes that
        gap, supersession or a status, is what this line should read
        instead.
        """
        remembered = self.plan_ids.get(plan_name)
        if remembered is not None:
            return remembered

        response = self.client.get("/plans", params={"name": plan_name})
        if response.status_code != 200:
            return None
        items: list[dict[str, Any]] = response.json()["items"]
        if not items:
            return None
        recovered: str = items[0]["plan_id"]
        self.plan_ids[plan_name] = recovered
        return recovered

    def plan_for(self, start: dict[str, Any]) -> str | None:
        """Find the plan for this plan_name, or author one if none exists.

        Authoring is what section 5 of the findings says an adapter must
        not do, and it stays here because the walk needs plans to exist
        and this spike has no operator to author them. A real reporter
        looks the name up and refuses the run when it finds nothing.
        """
        plan_name = str(start.get("plan_name"))
        found = self.plan_id_for(plan_name)
        if found is not None:
            return found

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
                "occurred_at": engine_time(doc),
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
        self._transition(run_uid, move, engine_time(doc))

    def on_stop(self, doc: dict[str, Any]) -> None:
        self.unmapped_stop |= set(doc) - STOP_KEYS_USED
        ending = ENDING_BY_EXIT_STATUS.get(str(doc.get("exit_status")))
        if ending is None:
            self.refused.append(f"no ending verb for exit_status {doc.get('exit_status')!r}")
            return
        self._transition(str(doc.get("run_start")), ending, engine_time(doc))

    def run_id_for(self, run_uid: str) -> str | None:
        """This adapter's id for an engine run, from memory or from AROC.

        The recovery a restarted adapter makes. Before `GET /runs` took a
        filter there was no second line here: a uid the map had lost was a
        run nothing could reach.

        The answer is a page rather than one record, because nothing stops
        two records of one engine run. Taking the first is this adapter's
        policy and not AROC's; a second row means somebody recorded the
        same run twice and that is worth knowing rather than hiding.
        """
        remembered = self.run_ids.get(run_uid)
        if remembered is not None:
            return remembered

        response = self.client.get(
            "/runs",
            params={
                "external_ref_scheme": EXTERNAL_REF_SCHEME,
                "external_ref_value": run_uid,
            },
        )
        if response.status_code != 200:
            return None
        items: list[dict[str, Any]] = response.json()["items"]
        if not items:
            return None
        if len(items) > 1:
            self.refused.append(
                f"{len(items)} runs recorded under uid {run_uid[:8]}; taking the first"
            )
        recovered: str = items[0]["run_id"]
        self.run_ids[run_uid] = recovered
        return recovered

    def _transition(self, run_uid: str, verb: str, at: str | None = None) -> None:
        run_id = self.run_id_for(run_uid)
        if run_id is None:
            self.refused.append(f"cannot {verb}: no run known for uid {run_uid[:8]}")
            return
        response = self.client.post(f"/runs/{run_id}/{verb}", json={"occurred_at": at})
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
        run_id = self.run_id_for(run_uid)
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

        print("\n--- the restart, demonstrated ---")
        print("Both dictionaries used to be the adapter's only way back. Clear them.")
        remembered = dict(adapter.run_ids)
        remembered_plans = dict(adapter.plan_ids)
        plans_before = len(list_plan_ids(client))
        adapter.refused.clear()
        adapter.run_ids.clear()
        adapter.plan_ids.clear()

        stop = next(
            entry["doc"]
            for entry in captured["completes"]["documents"]
            if entry["name"] == "stop"
        )
        recovered = adapter.run_id_for(str(stop["run_start"]))
        print(f"  the run half: GET /runs by uid gives {recovered}")
        print(f"  which is the id it held before the restart: {recovered in remembered.values()}")
        adapter.on_stop(stop)
        print(f"  and replaying the stop document now gets: {adapter.refused}")
        print(
            "  which is the right refusal and a different one. It used to be "
            "'no run known for uid'; it is now the domain saying that ending "
            "already happened, which is a run the adapter can see rather than "
            "one it has lost."
        )

        recovered_plan = adapter.plan_id_for("count")
        print(f"\n  the plan half: GET /plans by name gives {recovered_plan}")
        print(
            "  which is the id it held before the restart: "
            f"{recovered_plan == remembered_plans.get('count')}"
        )
        start = next(
            entry["doc"]
            for entry in captured["real_plan"]["documents"]
            if entry["name"] == "start"
        )
        adapter.plan_for(start)
        plans_after = len(list_plan_ids(client))
        print(f"  and plans defined before the restart and after: {plans_before}, {plans_after}")
        print(
            "  which is the whole of the fix. A restarted adapter used to "
            "author `count` a second time, leaving two plans where an "
            "operator wrote one, and every later run pointing at whichever "
            "the adapter happened to be holding."
        )
        print(
            "  what it still cannot answer is which of two plans named `count` "
            "is current when an operator really did write two. It takes the "
            "newest and says so here rather than pretending that is the same "
            "question."
        )
        adapter.run_ids.update(remembered)
        adapter.plan_ids.update(remembered_plans)

        print("\n--- a redelivered start, demonstrated ---")
        print("An adapter that reconnects and replays will send a start it already sent.")
        adapter.refused.clear()
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

        # The two gaps meet here. Nothing refuses a duplicate on the way
        # in, so the lookup that fixes the restart now has three answers
        # to give, and it says so rather than picking one quietly.
        adapter.run_ids.clear()
        adapter.refused.clear()
        adapter.run_id_for(str(first_start["uid"]))
        print(f"  a restart after that would find: {adapter.refused or 'one run'}")


if __name__ == "__main__":
    main()
