"""One motor, two ophyd objects, and what a device claim can key on.

`collide.py` found that the hazard is two writers on one device rather
than concurrency as such. That leaves the question this asks: when a
procedure step declares the devices it touches, what is the unit of the
declaration?

The obvious answer is the object a startup profile builds, and it is
wrong. `spikes/ophyd_adapter/` established that an ophyd Device's name
and extent are client-side opinions, by building one station under two
names against one IOC. This takes the next step and measures what that
costs: not merely that two declarations can look disjoint while naming
one motor, but that ophyd's own completion logic breaks when they do.

## What is real here and what is not

Real: the motor record, both ophyd objects, and every method called on
them. Nothing is patched. The control is taken before the second object
exists, in the same process, because that is when contamination starts.

Not real: nothing. There is no detector here and no plan.

Run it with:

    uv run --with caproto --with ophyd --with pyepics \\
        python spikes/conductor/shared_device.py
"""

from __future__ import annotations

import json
import multiprocessing
import time
from pathlib import Path
from typing import Any

from ioc import SCANNED, localhost_only, serve

localhost_only()

SETTLE_SECONDS = 1.0
WATCH_SECONDS = 6.0


def timed_move(motor: Any, target: float) -> dict[str, Any]:
    """One blocking move, and whether it was still moving when it returned."""
    started = time.time()
    motor.move(target, wait=True, timeout=60)
    elapsed = time.time() - started
    return {
        "asked": target,
        "returned_after": round(elapsed, 2),
        "position_on_return": round(motor.position, 4),
        "arrived": abs(motor.position - target) < 0.01,
    }


def main() -> None:
    server = multiprocessing.Process(target=serve, daemon=True)
    server.start()
    time.sleep(3)

    from ophyd import EpicsMotor, EpicsSignal

    # The control, taken while only one object exists.
    first = EpicsMotor(SCANNED, name="station_sample_x")
    first.wait_for_connection(timeout=15)
    first.move(0.0, wait=True, timeout=60)
    time.sleep(SETTLE_SECONDS)
    alone = [timed_move(first, 1.0), timed_move(first, 5.0)]

    # A second profile binds the same motor under its own name.
    second = EpicsMotor(SCANNED, name="tomo_sample_x")
    second.wait_for_connection(timeout=15)

    first.move(0.0, wait=True, timeout=60)
    time.sleep(SETTLE_SECONDS)
    shared = [timed_move(first, 1.0), timed_move(second, 5.0)]

    watched: list[dict[str, Any]] = []
    started = time.time()
    while time.time() - started < WATCH_SECONDS:
        watched.append({"after": round(time.time() - started, 1), "position": round(second.position, 4)})
        time.sleep(0.5)

    description = EpicsSignal(f"{SCANNED}.DESC", name="description", string=True)
    description.wait_for_connection(timeout=15)
    as_served = description.get()
    description.put("anything a client likes", wait=True)
    time.sleep(0.5)
    after_write = description.get()

    result = {
        "one_object": alone,
        "two_objects": shared,
        "after_the_second_move_returned": watched,
        "names": {
            "first": first.name,
            "second": second.name,
            "first_read_keys": list(first.read()),
            "second_read_keys": list(second.read()),
            "shared_keys": sorted(set(first.read()) & set(second.read())),
            "same_underlying_pv": first.user_setpoint.pvname == second.user_setpoint.pvname,
            "underlying_pv": first.user_setpoint.pvname,
        },
        "desc_field": {
            "as_served": as_served,
            "after_a_write": after_write,
            "writable_by_any_client": as_served != after_write,
        },
    }

    out = Path(__file__).with_name("shared_device.json")
    out.write_text(json.dumps(result, indent=2) + "\n")

    print("one object, in sequence")
    for row in alone:
        print(f"    move({row['asked']}) returned after {row['returned_after']:>5}s"
              f"  at {row['position_on_return']:>7}  arrived={row['arrived']}")
    print("two objects, same motor")
    for row in shared:
        print(f"    move({row['asked']}) returned after {row['returned_after']:>5}s"
              f"  at {row['position_on_return']:>7}  arrived={row['arrived']}")
    print("where it actually went afterwards")
    for row in watched:
        print(f"    +{row['after']:>4}s  {row['position']}")
    print(f"\nsame underlying pv  {result['names']['underlying_pv']}"
          f"  shared read keys {result['names']['shared_keys']}")
    print(f"DESC as served      {as_served!r}  after a write {after_write!r}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
