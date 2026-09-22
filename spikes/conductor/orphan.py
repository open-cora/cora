"""Kill the driver mid-scan and look at what is left.

If a conductor holds the state of a procedure in its own memory, the
question that decides whether that is survivable is what the world looks
like the instant it dies. This kills a driving process at a known point
and then watches the IOC and the document stream.

## What is real here and what is not

Real: the motor record, the motion, and the kill. The driver is a
separate process running a real `RunEngine` over a real `EpicsMotor`, and
it is sent SIGKILL, which is what a machine losing power does to a
process and what a container runtime does after a failed liveness check.
Nothing is given a chance to clean up, because the case worth measuring
is the one where nothing was.

Not real: the detector, for the reason `collide.py` gives.

Run it with:

    uv run --with caproto --with ophyd --with bluesky --with pyepics \\
        python spikes/conductor/orphan.py
"""

from __future__ import annotations

import json
import multiprocessing
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from ioc import SCANNED, localhost_only, serve

localhost_only()

KILL_AFTER = 3.0
"""Seconds into the scan at which the driver dies.

Three points across the motor's full travel, so each move takes about
five seconds at velocity 1.0 and this lands squarely inside the second
one. Killing it between moves would measure something easier.
"""

WATCH_SECONDS = 12.0
"""How long to keep watching the IOC after the driver is gone."""


def driver(directive: str, report: Any) -> None:
    """A conductor driving one scan, about to be killed partway through.

    It reports the run's identity as soon as the engine mints it, which
    is the last thing anyone outside this process will ever learn about
    this run.
    """
    localhost_only()

    from bluesky import RunEngine
    from bluesky.plans import scan
    from ophyd import EpicsMotor
    from ophyd.sim import SynGauss

    motor = EpicsMotor(SCANNED, name="mtr")
    motor.wait_for_connection(timeout=15)
    detector = SynGauss("det", motor, "mtr", center=2.5, Imax=100, sigma=1.0)

    engine = RunEngine({})
    engine.subscribe(lambda name, doc: report.put({"document": name, "uid": doc.get("uid")}))
    engine(scan([detector], motor, 0, 10, 3), aroc_directive_id=directive)


def observe(motor: Any, setpoint: Any, moving: Any, done: Any) -> dict[str, Any]:
    """One look at the motor, from outside whatever was driving it."""
    return {
        "at": round(time.time(), 3),
        "readback": round(motor.position, 4),
        "setpoint": round(setpoint.get(), 4),
        "moving": int(moving.get()),
        "done_moving": int(done.get()),
    }


def main() -> None:
    server = multiprocessing.Process(target=serve, daemon=True)
    server.start()
    time.sleep(3)

    from ophyd import EpicsMotor, EpicsSignal

    motor = EpicsMotor(SCANNED, name="mtr")
    setpoint = EpicsSignal(f"{SCANNED}.VAL", name="setpoint")
    moving = EpicsSignal(f"{SCANNED}.MOVN", name="moving")
    done = EpicsSignal(f"{SCANNED}.DMOV", name="done")
    for signal_ in (motor, setpoint, moving, done):
        signal_.wait_for_connection(timeout=15)

    motor.move(0, wait=True, timeout=30)
    time.sleep(1.0)

    directive = str(uuid.uuid4())
    report: Any = multiprocessing.Queue()
    conductor = multiprocessing.Process(target=driver, args=(directive, report), daemon=True)

    before = observe(motor, setpoint, moving, done)
    conductor.start()
    started = time.time()
    time.sleep(KILL_AFTER)

    at_kill = observe(motor, setpoint, moving, done)
    conductor.kill()
    conductor.join(10)

    watched: list[dict[str, Any]] = []
    while time.time() - started < KILL_AFTER + WATCH_SECONDS:
        watched.append(observe(motor, setpoint, moving, done))
        time.sleep(0.5)

    documents: list[dict[str, Any]] = []
    while not report.empty():
        documents.append(report.get())

    result = {
        "directive_minted": directive,
        "killed_with": signal.SIGKILL.name,
        "killed_seconds_in": KILL_AFTER,
        "exit_code": conductor.exitcode,
        "before": before,
        "at_kill": at_kill,
        "after": watched,
        "documents_seen": [d["document"] for d in documents],
        "run_uid": next((d["uid"] for d in documents if d["document"] == "start"), None),
        "stop_seen": any(d["document"] == "stop" for d in documents),
        "settled": {
            "readback": watched[-1]["readback"],
            "setpoint": watched[-1]["setpoint"],
            "moving": watched[-1]["moving"],
            "done_moving": watched[-1]["done_moving"],
        },
    }

    out = Path(__file__).with_name("orphan.json")
    out.write_text(json.dumps(result, indent=2) + "\n")

    print(f"driver exit code   {result['exit_code']}")
    print(f"run uid            {result['run_uid']}")
    print(f"documents          {result['documents_seen']}")
    print(f"stop document      {result['stop_seen']}")
    print(f"at kill            {at_kill}")
    for row in watched:
        print(
            f"  +{row['at'] - at_kill['at']:>5.1f}s  readback {row['readback']:>8}"
            f"  setpoint {row['setpoint']:>6}  moving {row['moving']}  dmov {row['done_moving']}"
        )
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
