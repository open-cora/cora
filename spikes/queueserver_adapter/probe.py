"""Drives a real RE Manager and writes down what it answered.

Five scenarios, one per open question. Nothing here is patched or
stubbed: the manager is the package's own `start-re-manager`, the queue
is in Redis, and both clients are ordinary ZMQ clients of the kind any
other agent at a beamline would be.

Run it with the manager already up. `README.md` has the two commands.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from bluesky_queueserver import ZMQCommSendThreads

ADDRESS = os.environ.get("AROC_SPIKE_ZMQ", "tcp://localhost:60715")
DOCUMENTS = Path(os.environ.get("AROC_SPIKE_DOCUMENTS", "documents.jsonl"))
DIRECTIVE = "aroc_directive_id"
POLL_SECONDS = 0.2


def client() -> ZMQCommSendThreads:
    return ZMQCommSendThreads(zmq_server_address=ADDRESS)


def call(conn: ZMQCommSendThreads, method: str, **params: object) -> dict:
    return conn.send_message(method=method, params=params or None)


def wait_idle(conn: ZMQCommSendThreads, limit: float = 90.0) -> str:
    deadline = time.time() + limit
    while time.time() < deadline:
        state = call(conn, "status").get("manager_state")
        if state == "idle":
            return state
        time.sleep(POLL_SECONDS)
    return f"still {state} after {limit}s"


def plan_item(name: str, *, meta: dict | None = None, **kwargs: object) -> dict:
    item: dict = {"name": name, "item_type": "plan", "kwargs": kwargs}
    if meta is not None:
        item["meta"] = meta
    return item


def documents() -> list[dict]:
    if not DOCUMENTS.exists():
        return []
    return [json.loads(line) for line in DOCUMENTS.read_text().splitlines() if line.strip()]


def fresh_documents() -> None:
    DOCUMENTS.unlink(missing_ok=True)


def open_environment(conn: ZMQCommSendThreads) -> None:
    if not call(conn, "status").get("worker_environment_exists"):
        call(conn, "environment_open")
        wait_idle(conn)


def identity(conn: ZMQCommSendThreads) -> dict:
    """Question 2 and 3: which names exist, when, and what reaches the run."""
    fresh_documents()
    call(conn, "history_clear")
    call(conn, "queue_clear")

    added = call(
        conn,
        "queue_item_add",
        item=plan_item("count", detectors=["det"], num=12, delay=0.4, meta={DIRECTIVE: "directive-1"}),
        user="aroc-conductor",
        user_group="primary",
    )
    item_uid = (added.get("item") or {}).get("item_uid")

    call(conn, "queue_start")
    first_seen_open: float | None = None
    uid_while_open: str | None = None
    started = time.time()
    while time.time() - started < 90:
        status = call(conn, "status")
        if status.get("manager_state") == "idle" and uid_while_open is not None:
            break
        runs = call(conn, "re_runs", option="open").get("run_list") or []
        if runs and uid_while_open is None:
            uid_while_open = runs[0].get("uid")
            first_seen_open = round(time.time() - started, 2)
        if status.get("manager_state") == "idle":
            break
        time.sleep(POLL_SECONDS)
    wait_idle(conn)

    history = call(conn, "history_get").get("items") or []
    result = (history[-1].get("result") if history else {}) or {}
    starts = [d["doc"] for d in documents() if d["name"] == "start"]
    stops = [d["doc"] for d in documents() if d["name"] == "stop"]

    return {
        "item_uid_at_submit": item_uid,
        "item_uid_is_a_run_uid": item_uid in (result.get("run_uids") or []),
        "run_uid_visible_while_open": uid_while_open,
        "seconds_until_run_uid_visible": first_seen_open,
        "run_uids_from_history": result.get("run_uids"),
        "exit_status_from_history": result.get("exit_status"),
        "exit_status_from_stop_document": stops[0].get("exit_status") if stops else None,
        "directive_in_start_document": starts[0].get(DIRECTIVE) if starts else None,
        "start_document_uid": starts[0].get("uid") if starts else None,
        "item_uid_in_start_document": (
            item_uid in json.dumps(starts[0], default=str) if starts else None
        ),
    }


def two_clients(conn: ZMQCommSendThreads) -> dict:
    """Question 1: two clients, one device, and whether anything objects."""
    call(conn, "history_clear")
    call(conn, "queue_clear")
    other = client()

    mine = call(
        conn,
        "queue_item_add",
        item=plan_item("move_and_count", detectors=["det"], mover="motor", target=1.0, num=2),
        user="aroc-conductor",
        user_group="primary",
    )
    theirs = call(
        other,
        "queue_item_add",
        item=plan_item("move_and_count", detectors=["det"], mover="motor", target=9.0, num=2),
        user="somebody-else",
        user_group="primary",
    )

    call(conn, "queue_start")
    wait_idle(conn)
    history = call(conn, "history_get").get("items") or []

    return {
        "conductor_add_succeeded": mine.get("success"),
        "other_client_add_succeeded": theirs.get("success"),
        "other_client_was_told_about_the_conflict": theirs.get("msg"),
        "items_executed": len(history),
        "exit_statuses": [(h.get("result") or {}).get("exit_status") for h in history],
        "users_recorded": [h.get("user") for h in history],
    }


def locking(conn: ZMQCommSendThreads) -> dict:
    """Question 1 again, through the mechanism queueserver actually offers."""
    call(conn, "queue_clear")
    other = client()

    locked = call(conn, "lock", lock_key="conductor-key", queue=True, user="aroc-conductor",
                  note="a walk is in progress")
    blocked = call(
        other,
        "queue_item_add",
        item=plan_item("count", detectors=["det"], num=1),
        user="somebody-else",
        user_group="primary",
    )
    with_key = call(
        other,
        "queue_item_add",
        item=plan_item("count", detectors=["det"], num=1),
        user="somebody-else",
        user_group="primary",
        lock_key="conductor-key",
    )
    environment_still_open = call(other, "status").get("worker_environment_exists")
    info = call(conn, "lock_info")
    call(conn, "unlock", lock_key="conductor-key")
    call(conn, "queue_clear")

    return {
        "lock_succeeded": locked.get("success"),
        "granularity": "whole queue and/or whole environment, never a device",
        "other_client_blocked": not blocked.get("success"),
        "refusal_message": blocked.get("msg"),
        "holder_named_in_refusal": "aroc-conductor" in str(blocked.get("msg", "")),
        "other_client_with_the_key_succeeded": with_key.get("success"),
        "reads_still_work_while_locked": environment_still_open is not None,
        "lock_info_user": (info.get("lock_info") or {}).get("user"),
    }


def execute_without_the_queue(conn: ZMQCommSendThreads) -> dict:
    """Question 4: is there a way to run one item now, and does it block?"""
    call(conn, "history_clear")
    call(conn, "queue_clear")
    started = time.time()
    answer = call(
        conn,
        "queue_item_execute",
        item=plan_item("count", detectors=["det"], num=6, delay=0.3),
        user="aroc-conductor",
        user_group="primary",
    )
    returned_after = round(time.time() - started, 2)
    state_right_after = call(conn, "status").get("manager_state")
    wait_idle(conn)
    finished_after = round(time.time() - started, 2)
    history = call(conn, "history_get").get("items") or []

    return {
        "accepted": answer.get("success"),
        "call_returned_after_seconds": returned_after,
        "manager_state_right_after_the_call": state_right_after,
        "plan_finished_after_seconds": finished_after,
        "item_uid_returned": (answer.get("item") or {}).get("item_uid"),
        "landed_in_history": len(history),
    }


def abandoned(conn: ZMQCommSendThreads) -> dict:
    """What a conductor comes back to: does the queue outlive its client?"""
    call(conn, "queue_clear")
    added = call(
        conn,
        "queue_item_add",
        item=plan_item("count", detectors=["det"], num=1),
        user="aroc-conductor",
        user_group="primary",
    )
    gone = client()
    still_there = call(gone, "queue_get").get("items") or []
    call(conn, "queue_clear")
    return {
        "queued_by_one_client": (added.get("item") or {}).get("item_uid"),
        "visible_to_another_client": [i.get("item_uid") for i in still_there],
        "queue_is_shared_state": bool(still_there),
    }


def main() -> int:
    conn = client()
    status = call(conn, "status")
    if not status.get("success", True) and not status.get("manager_state"):
        print("no manager on", ADDRESS, file=sys.stderr)
        return 1
    open_environment(conn)

    import bluesky
    import bluesky_queueserver

    findings = {
        "queueserver_version": bluesky_queueserver.__version__,
        "bluesky_version": bluesky.__version__,
        "identity": identity(conn),
        "two_clients": two_clients(conn),
        "locking": locking(conn),
        "execute_without_the_queue": execute_without_the_queue(conn),
        "abandoned": abandoned(conn),
    }
    Path("findings.json").write_text(json.dumps(findings, indent=2, default=str) + "\n")
    print(json.dumps(findings, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
