"""Drives a real blueapi service and writes down what it answered.

Five scenarios, one per open question. Nothing here is patched or stubbed:
the service is the package's own `blueapi serve`, the message bus is a
real RabbitMQ with its STOMP plugin on, and the HTTP client is plain
httpx of the kind any other client at a beamline would use.

The document subscriber is the interesting half. It joins the bus the way
`apps/reporter` would have to, reads whatever arrives on the worker's
topic, and keeps the headers as well as the bodies, because question 2 is
entirely about a header.

Run it with the service and the broker already up. `README.md` has the
commands.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import stomp

API = os.environ.get("AROC_SPIKE_API", "http://localhost:8765")
BUS_HOST = os.environ.get("AROC_SPIKE_BUS_HOST", "localhost")
BUS_PORT = int(os.environ.get("AROC_SPIKE_BUS_PORT", "61618"))
TOPIC = os.environ.get("AROC_SPIKE_TOPIC", "/topic/public.worker.event")
CAPTURE = Path(os.environ.get("AROC_SPIKE_CAPTURE", "findings.json"))

POLL_SECONDS = 0.1


class Collector(stomp.ConnectionListener):
    """Everything the bus delivered, headers kept.

    A reporter would decode and discard most of this. Here the headers are
    the point: question 2 asks which of them, if any, ties a document back
    to the task that was submitted, and the answer cannot be seen from the
    body.
    """

    def __init__(self) -> None:
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def on_message(self, frame: Any) -> None:
        try:
            body = json.loads(frame.body)
        except ValueError:
            body = {"unparsed": frame.body[:200]}
        self.messages.put(
            {"at": time.monotonic(), "headers": dict(frame.headers), "body": body}
        )

    def drain(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while True:
            try:
                out.append(self.messages.get_nowait())
            except queue.Empty:
                return out


def listen() -> tuple[stomp.Connection, Collector]:
    collector = Collector()
    conn = stomp.Connection([(BUS_HOST, BUS_PORT)], heartbeats=(10000, 10000))
    conn.set_listener("collector", collector)
    conn.connect("guest", "guest", wait=True)
    conn.subscribe(destination=TOPIC, id="aroc-spike", ack="auto")
    return conn, collector


SESSION = os.environ.get("AROC_SPIKE_SESSION", "cm12345-1")
"""The instrument session every task must name.

Required by `TaskRequest`, and there is no way to omit it. The value is
Diamond's visit format. Nothing here checks it, which is question 4's
business; what matters is that a client must supply one.
"""


def submit(plan: str, params: dict[str, Any], **extra: Any) -> httpx.Response:
    """One task, submitted the way the live schema demands.

    `extra` exists for the half of question 2 that asks whether a caller
    can attach its own reference. `TaskRequest` sets
    `additionalProperties: false`, so anything passed here should come
    back refused, and the refusal is the measurement.
    """
    body = {"name": plan, "params": params, "instrument_session": SESSION, **extra}
    return httpx.post(f"{API}/tasks", json=body, timeout=30)


def start(task_id: str) -> httpx.Response:
    return httpx.put(f"{API}/worker/task", json={"task_id": task_id}, timeout=30)


def task(task_id: str) -> dict[str, Any]:
    return httpx.get(f"{API}/tasks/{task_id}", timeout=30).json()


def state() -> str:
    return str(httpx.get(f"{API}/worker/state", timeout=30).json())


def wait_idle(limit: float = 90.0) -> str:
    deadline = time.monotonic() + limit
    seen = "?"
    while time.monotonic() < deadline:
        seen = state()
        if "IDLE" in seen.upper():
            return seen
        time.sleep(POLL_SECONDS)
    return f"still {seen} after {limit}s"


def run_to_completion(plan: str, params: dict[str, Any]) -> dict[str, Any]:
    """Submit, start, and poll until the worker says it is done.

    This is the shape a conductor would have to adopt, and writing it out
    is half of question 1: there is no call here that blocks until the
    plan is finished.
    """
    submitted = submit(plan, params)
    task_id = submitted.json()["task_id"]
    started_at = time.monotonic()
    start(task_id)
    polls = 0
    while time.monotonic() - started_at < 90.0:
        polls += 1
        current = task(task_id)
        if current.get("is_complete"):
            return {
                "task_id": task_id,
                "seconds": round(time.monotonic() - started_at, 3),
                "polls": polls,
                "task": current,
            }
        time.sleep(POLL_SECONDS)
    return {"task_id": task_id, "timed_out": True, "task": task(task_id)}


def scenario_1_busy(collector: Collector) -> dict[str, Any]:
    """What a second client is told while the worker is running.

    ADR 0003 says the worker "will return an error if asked to execute one
    task while another is running". What matters to a conductor is whether
    that error is distinguishable from every other 4xx and whether it says
    who is holding the worker, because `Refused` carries a holder and
    `Broke` does not.
    """
    wait_idle()
    collector.drain()

    first = submit("slow_count", {"num": 6, "delay": 0.5})
    first_id = first.json()["task_id"]
    start(first_id)
    time.sleep(0.5)

    during = state()
    second = submit("quick_count", {"num": 1})
    second_id = second.json().get("task_id") if second.status_code < 300 else None
    collision = start(second_id) if second_id else None

    outcome = {
        "state_while_running": during,
        "submitting_a_second_task": {
            "status": second.status_code,
            "body": second.json() if second.content else None,
        },
        "starting_it_while_busy": (
            {
                "status": collision.status_code,
                "body": collision.json() if collision.content else None,
                "text": collision.text[:400],
            }
            if collision is not None
            else None
        ),
    }
    wait_idle()
    return outcome


def scenario_2_correlation(collector: Collector) -> dict[str, Any]:
    """Which header, if any, ties a document back to the submitted task.

    The events documentation names `correlation-id` under STOMP. The
    application config names `traceparent` as its context header. Those
    are not the same thing and only one of them can be the join, so this
    reads whatever actually arrives.
    """
    wait_idle()
    carrying = submit("quick_count", {"num": 1}, metadata={"aroc_directive_id": "directive-1"})
    refused_metadata = {
        "status": carrying.status_code,
        "body": carrying.json() if carrying.content else None,
    }
    if carrying.status_code < 300:
        wait_idle()

    collector.drain()
    ran = run_to_completion("quick_count", {"num": 1})
    time.sleep(1.0)
    messages = collector.drain()

    documents = [m for m in messages if isinstance(m["body"], dict) and "name" in m["body"]]
    header_names = sorted({k for m in messages for k in m["headers"]})
    starts = [m for m in documents if m["body"].get("name") == "start"]
    stops = [m for m in documents if m["body"].get("name") == "stop"]

    return {
        "submitting_a_directive_id_of_our_own": refused_metadata,
        "task_id": ran["task_id"],
        "messages_on_the_bus": len(messages),
        "document_messages": len(documents),
        "document_names": [m["body"].get("name") for m in documents],
        "every_header_seen": header_names,
        "headers_on_the_start": starts[0]["headers"] if starts else None,
        "task_id_appears_in_a_header": any(
            ran["task_id"] in str(v) for m in messages for v in m["headers"].values()
        ),
        "run_uid_in_the_start": (
            starts[0]["body"].get("doc", {}).get("uid") if starts else None
        ),
        "task_id_inside_the_start_document": (
            ran["task_id"] in json.dumps(starts[0]["body"]) if starts else None
        ),
        "stop_document_exit_status": (
            stops[0]["body"].get("doc", {}).get("exit_status") if stops else None
        ),
    }


def scenario_3_reporter_shape(collector: Collector) -> dict[str, Any]:
    """Whether what arrives is already `(name, document)`.

    `apps/reporter` takes documents as that pair and `translate.py` is
    written against it. If the bus delivers the same pair inside a JSON
    envelope, then only `sources.py` is new and the translator is
    untouched, which is the difference between a source and a rewrite.
    """
    wait_idle()
    collector.drain()
    run_to_completion("quick_count", {"num": 2})
    time.sleep(1.0)
    messages = collector.drain()

    envelopes = [m["body"] for m in messages if isinstance(m["body"], dict)]
    document_like = [e for e in envelopes if set(e) >= {"name", "doc"}]
    other = [sorted(e) for e in envelopes if not set(e) >= {"name", "doc"}]

    return {
        "envelope_keys_seen": sorted({k for e in envelopes for k in e}),
        "document_envelopes": len(document_like),
        "one_envelope": document_like[0] if document_like else None,
        "non_document_envelope_shapes": other[:6],
        "pairs_a_translator_would_get": [
            (e["name"], sorted(e["doc"])[:6]) for e in document_like[:4]
        ],
    }


def scenario_4_what_it_needed() -> dict[str, Any]:
    """What the service is serving, given a config with five things missing.

    Diamond's system-test config carries oidc, tiled, numtracker and opa.
    None of them is here. If the plans list answers, then those are their
    deployment rather than the package's requirements.
    """
    plans = httpx.get(f"{API}/plans", timeout=30).json()
    devices = httpx.get(f"{API}/devices", timeout=30).json()
    health = httpx.get(f"{API}/healthz", timeout=30)
    try:
        oidc = httpx.get(f"{API}/config/oidc", timeout=30)
        oidc_said = {"status": oidc.status_code, "body": oidc.text[:200]}
    except httpx.HTTPError as exc:
        oidc_said = {"error": str(exc)}

    return {
        "plans_registered": [p.get("name") for p in plans.get("plans", [])],
        "devices_registered": [d.get("name") for d in devices.get("devices", [])],
        "healthz": health.status_code,
        "config_oidc_without_an_oidc_provider": oidc_said,
        "a_plan_schema": next(
            (p.get("schema") for p in plans.get("plans", []) if p.get("name") == "slow_count"),
            None,
        ),
    }


def scenario_5_two_vocabularies(collector: Collector) -> dict[str, Any]:
    """Whether the plan-level events agree with the run's own stop document.

    Queueserver's history and the stop document disagreed, six statuses
    against three. blueapi adds its own plan-level events instead. This
    reads both for one run and puts them side by side.
    """
    wait_idle()
    collector.drain()
    ran = run_to_completion("quick_count", {"num": 1})
    time.sleep(1.0)
    messages = collector.drain()
    failed = scenario_5_the_failure_path(collector)

    worker_events = [
        m["body"]
        for m in messages
        if isinstance(m["body"], dict) and not set(m["body"]) >= {"name", "doc"}
    ]
    stops = [
        m["body"]
        for m in messages
        if isinstance(m["body"], dict) and m["body"].get("name") == "stop"
    ]

    return {
        "the_task_as_rest_reports_it": {
            "is_complete": ran["task"].get("is_complete"),
            "errors": ran["task"].get("errors"),
            "outcome": ran["task"].get("outcome"),
        },
        "stop_document_exit_status": (
            stops[0].get("doc", {}).get("exit_status") if stops else None
        ),
        "worker_events": worker_events[:8],
        "seconds_and_polls": {"seconds": ran["seconds"], "polls": ran["polls"]},
        "the_failure_path": failed,
    }


def scenario_5_the_failure_path(collector: Collector) -> dict[str, Any]:
    """The same two readings for a plan that raises after opening a run.

    Success agreeing with success says little. The queueserver finding was
    that two vocabularies described different things, and the way to see
    that is a run where the plan failed and ask both halves what happened.
    """
    wait_idle()
    collector.drain()
    ran = run_to_completion("failing_count", {"num": 2})
    time.sleep(1.0)
    messages = collector.drain()

    stops = [
        m["body"]
        for m in messages
        if isinstance(m["body"], dict) and m["body"].get("name") == "stop"
    ]
    finals = [
        m["body"]
        for m in messages
        if isinstance(m["body"], dict)
        and (m["body"].get("task_status") or {}).get("task_complete")
    ]

    return {
        "rest_says": {
            "is_complete": ran["task"].get("is_complete"),
            "errors": ran["task"].get("errors"),
            "outcome": ran["task"].get("outcome"),
        },
        "stop_document": {
            "exit_status": stops[0].get("doc", {}).get("exit_status") if stops else None,
            "reason": stops[0].get("doc", {}).get("reason") if stops else None,
        },
        "the_final_worker_event": finals[-1] if finals else None,
        "a_stop_document_was_published": bool(stops),
    }


def main() -> None:
    try:
        httpx.get(f"{API}/healthz", timeout=5)
    except httpx.HTTPError:
        sys.exit(f"no blueapi at {API}. Start it first; README.md has the command.")

    conn, collector = listen()
    try:
        findings = {
            "1_busy": scenario_1_busy(collector),
            "2_correlation": scenario_2_correlation(collector),
            "3_reporter_shape": scenario_3_reporter_shape(collector),
            "4_what_it_needed": scenario_4_what_it_needed(),
            "5_two_vocabularies": scenario_5_two_vocabularies(collector),
        }
    finally:
        conn.disconnect()

    CAPTURE.write_text(json.dumps(findings, indent=2, default=str) + "\n")
    print(json.dumps(findings, indent=2, default=str))
    print(f"\nwritten to {CAPTURE}", file=sys.stderr)


if __name__ == "__main__":
    main()
