"""Two writers, one motor, and whether anything notices.

The conductor sketch puts a control seam (EPICS, Tango) and an
acquisition seam (Bluesky, TomoScan) behind one procedure, so a step can
move a device and a later step can scan it. Nothing in that sketch stops
a step from moving a device while a scan owns it. This asks what happens
when one does.

## What is real here and what is not

Real: the motor record, served by caproto's own simulator over Channel
Access; ophyd's `EpicsMotor`, connected to it the way it connects to a
beamline; and Bluesky's `scan`, run by a real `RunEngine` that is told
nothing about any of this. The rival writes go out of a separate process
through pyepics, which is what a control seam that is not the acquisition
engine actually looks like from the IOC's side.

Not real: the detector. `SynGauss` computes a value from the motor's
position rather than reading a camera, so the data recorded is a function
of where the motor actually was. That is the property the scenarios below
need, and a real detector would only make the corruption harder to see.

So a difference between scenarios is produced by the rival write, by
ophyd's own move logic and by the RunEngine's own error handling. Nothing
here inspects or patches any of the three.

## The scenarios

    undisturbed     nothing interferes, and this is the baseline
    rival_move      the rival sends the scanned motor somewhere else
    rival_stop      the rival stops the scanned motor
    rival_hold      the rival sets SPMG to Stop, which is sticky
    other_device    the rival moves a motor the scan does not own
    correlation_id  no rival, asking instead what identity a caller holds

The last one is a different question sharing a harness. See its own
section in FINDINGS.

Run it with:

    uv run --with caproto --with ophyd --with bluesky --with pyepics \\
        python spikes/conductor/collide.py
"""

from __future__ import annotations

import json
import multiprocessing
import time
import uuid
from pathlib import Path
from typing import Any

from ioc import SCANNED, UNSCANNED, localhost_only, serve

localhost_only()

SETTLE_SECONDS = 1.0
"""Long enough for a move to finish reporting after it stops."""

INTERFERE_AFTER = 1.5
"""Seconds the rival waits before writing, measured from its own start.

The scan takes about five seconds, so this lands somewhere in its middle.
The exact point does not matter and is recorded per scenario anyway,
because what is being asked is whether a write during a move is noticed
at all, not whether some particular millisecond is special.
"""


def rival(pv: str, value: Any, delay: float, report: Any) -> None:
    """A control client that is not the acquisition engine.

    Its own process, so nothing it does can be explained by sharing a
    Channel Access context with ophyd. This is the closest thing here to
    a control seam step: connect, put, leave.
    """
    localhost_only()

    import epics

    time.sleep(delay)
    epics.caput(pv, value, wait=True, timeout=10)
    report.put({"pv": pv, "value": value, "at": time.time()})


def _readings(docs: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """What the scan wrote down at each point.

    The setpoint is where the scan asked the motor to be and the readback
    is where it was when the reading was taken. In an undisturbed scan
    they agree to within the motor's resolution, and the gap between them
    is the whole measurement in the scenarios below.
    """
    out: list[dict[str, Any]] = []
    for name, doc in docs:
        if name != "event":
            continue
        data = doc["data"]
        out.append(
            {
                "setpoint": round(data["mtr_user_setpoint"], 4),
                "readback": round(data["mtr"], 4),
                "det": round(data["det"], 4),
            }
        )
    return out


def scenario(
    name: str,
    engine: Any,
    motor: Any,
    detector: Any,
    *,
    rival_pv: str | None = None,
    rival_value: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One scan, with whatever wrote to the IOC while it ran."""
    from bluesky.plans import scan as scan_plan

    docs: list[tuple[str, dict[str, Any]]] = []
    token = engine.subscribe(lambda n, d: docs.append((n, d)))

    report: Any = multiprocessing.Queue()
    interferer = None
    if rival_pv is not None:
        interferer = multiprocessing.Process(
            target=rival, args=(rival_pv, rival_value, INTERFERE_AFTER, report), daemon=True
        )
        interferer.start()

    started = time.time()
    raised: str | None = None
    try:
        engine(scan_plan([detector], motor, 0, 5, 6), **(metadata or {}))
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started

    if interferer is not None:
        interferer.join(20)
    engine.unsubscribe(token)
    time.sleep(SETTLE_SECONDS)

    wrote = report.get() if not report.empty() else None
    starts = [d for n, d in docs if n == "start"]
    stops = [d for n, d in docs if n == "stop"]

    return {
        "scenario": name,
        "rival_wrote": None
        if wrote is None
        else {"pv": wrote["pv"], "value": wrote["value"], "seconds_in": round(wrote["at"] - started, 2)},
        "raised": raised,
        "seconds": round(elapsed, 1),
        "exit_status": stops[0]["exit_status"] if stops else None,
        "reason": stops[0].get("reason") if stops else None,
        "num_events": stops[0].get("num_events") if stops else None,
        "readings": _readings(docs),
        "start_keys_added": sorted(set(starts[0]) - _BASELINE_START_KEYS) if starts else [],
        "directive_in_start": starts[0].get("aroc_directive_id") if starts else None,
        "run_uid": starts[0].get("uid") if starts else None,
        "position_after": round(motor.position, 4),
    }


_BASELINE_START_KEYS: set[str] = set()
"""Filled from the undisturbed run, so the last scenario can show its own."""


def reset(motor: Any, spmg: Any) -> dict[str, Any]:
    """Put the motor back where a scenario expects to find it.

    Returns what had to be undone, because one of the scenarios leaves
    something behind and a reset that silently fixed it would hide the
    finding.
    """
    held = spmg.get(as_string=True)
    if held != "Go":
        spmg.put("Go", wait=True)
        time.sleep(SETTLE_SECONDS)

    moved_home = True
    try:
        motor.move(0, wait=True, timeout=30)
    except Exception:  # noqa: BLE001
        moved_home = False
    time.sleep(SETTLE_SECONDS)
    return {"spmg_found": held, "returned_home": moved_home}


def main() -> None:
    server = multiprocessing.Process(target=serve, daemon=True)
    server.start()
    time.sleep(3)

    from bluesky import RunEngine
    from ophyd import EpicsMotor, EpicsSignal
    from ophyd.sim import SynGauss

    motor = EpicsMotor(SCANNED, name="mtr")
    other = EpicsMotor(UNSCANNED, name="other")
    spmg = EpicsSignal(f"{SCANNED}.SPMG", name="spmg", string=True)
    for signal in (motor, other, spmg):
        signal.wait_for_connection(timeout=15)

    detector = SynGauss("det", motor, "mtr", center=2.5, Imax=100, sigma=1.0)
    engine = RunEngine({})

    results: list[dict[str, Any]] = []
    resets: list[dict[str, Any]] = []

    undisturbed = scenario("undisturbed", engine, motor, detector)
    results.append(undisturbed)
    resets.append({"after": "undisturbed", **reset(motor, spmg)})

    for name, pv, value in (
        ("rival_move", f"{SCANNED}.VAL", 9.0),
        ("rival_stop", f"{SCANNED}.STOP", 1),
        ("rival_hold", f"{SCANNED}.SPMG", "Stop"),
        ("other_device", f"{UNSCANNED}.VAL", 3.0),
    ):
        results.append(scenario(name, engine, motor, detector, rival_pv=pv, rival_value=value))
        resets.append({"after": name, **reset(motor, spmg)})

    # Question 2 shares the harness and asks something else entirely: what
    # a caller holds at submit time that it still holds afterwards.
    _BASELINE_START_KEYS.update(_start_keys_of(engine, motor, detector))

    directive = str(uuid.uuid4())
    tagged = scenario(
        "correlation_id",
        engine,
        motor,
        detector,
        metadata={"aroc_directive_id": directive},
    )
    tagged["directive_minted"] = directive
    results.append(tagged)
    resets.append({"after": "correlation_id", **reset(motor, spmg)})

    out = Path(__file__).with_name("collisions.json")
    out.write_text(json.dumps({"scenarios": results, "resets": resets}, indent=2) + "\n")

    for row in results:
        print(f"\n--- {row['scenario']}")
        print(f"    rival        {row['rival_wrote']}")
        print(f"    exit_status  {row['exit_status']}  raised={row['raised']}")
        print(f"    events       {row['num_events']}  in {row['seconds']}s")
        print(f"    position     {row['position_after']}")
        for reading in row["readings"]:
            gap = round(reading["readback"] - reading["setpoint"], 3)
            flag = "   <-- off" if abs(gap) > 0.01 else ""
            print(f"      asked {reading['setpoint']:>6}  got {reading['readback']:>8}{flag}")
    print(f"\nwrote {out}")


def _start_keys_of(engine: Any, motor: Any, detector: Any) -> set[str]:
    """Keys a start document carries when the caller adds nothing.

    Run as its own short scan rather than reused from the baseline,
    because the baseline ran before this function existed as a question
    and a key set is cheap to take again.
    """
    from bluesky.plans import count

    seen: list[dict[str, Any]] = []
    token = engine.subscribe(lambda n, d: seen.append(d) if n == "start" else None)
    engine(count([detector], num=1))
    engine.unsubscribe(token)
    return set(seen[0]) if seen else set()


if __name__ == "__main__":
    main()
