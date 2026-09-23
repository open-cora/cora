"""Drives a real IOC with access security on and writes down what it refused.

Five scenarios, one per open question. Nothing here is patched. The IOC is
EPICS base's own `softIoc` reading a database and an access configuration
file, and every write goes out through pyepics, which is the library
`conductor.adapters.epics_control` uses.

Run it with the IOC already up. `README.md` has the two commands.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import epics

PREFIX = os.environ.get("AROC_SPIKE_PREFIX", "aroc-as:")
CAPTURE = Path(os.environ.get("AROC_SPIKE_CAPTURE", "findings.json"))

M1 = f"{PREFIX}m1"
M2 = f"{PREFIX}m2"
FREE = f"{PREFIX}free"
CLAIM_M1 = f"{PREFIX}claim:m1"
CLAIM_M2 = f"{PREFIX}claim:m2"

SETTLE = 0.3
"""Long enough for an access-rights message to cross a loopback socket.

The point of scenario 1 is to measure this rather than assume it, so this
is used only where a test has already made its measurement and wants the
next one to start from a settled state.
"""


def connect(name: str) -> epics.PV:
    pv = epics.PV(name, connection_timeout=5.0)
    if not pv.wait_for_connection(timeout=5.0):
        sys.exit(f"no IOC serving {name}. Start it first; README.md has the command.")
    return pv


def attempt(pv: epics.PV, value: float) -> dict[str, object]:
    """One write, and everything observable about how it went.

    `put` is given `wait=True` so a refusal has somewhere to show up other
    than in the value failing to change later. What is recorded is what an
    adapter could act on: the return, whether anything raised, the client's
    idea of its own permission, and the value afterwards.
    """
    before = pv.get()
    raised: str | None = None
    returned: object = None
    try:
        returned = pv.put(value, wait=True)
    except Exception as exc:
        raised = f"{type(exc).__name__}: {exc}"
    time.sleep(SETTLE)
    after = pv.get(use_monitor=False)
    return {
        "record": pv.pvname,
        "asked": value,
        "write_access": pv.write_access,
        "read_access": pv.read_access,
        "put_returned": returned,
        "raised": raised,
        "value_before": before,
        "value_after": after,
        "value_changed": before != after,
    }


def set_gate(gate: epics.PV, value: int) -> None:
    gate.put(value, wait=True)
    time.sleep(SETTLE)


def scenario_1_the_gate(m1: epics.PV, claim: epics.PV) -> dict[str, object]:
    """Does a CALC-gated rule actually decide a write, and when.

    The timing half matters as much as the yes or no. A conductor that
    claims a device and writes to it immediately is racing the IOC's
    notification, and if the gate takes a human-visible time to arrive then
    a claim is not something a step can take at its start.
    """
    seen: list[tuple[float, bool]] = []

    def watch(read_access: bool, write_access: bool, **_: object) -> None:
        seen.append((time.monotonic(), bool(write_access)))

    m1.access_callbacks.append(watch)

    set_gate(claim, 0)
    unclaimed = attempt(m1, 1.0)

    seen.clear()
    asked_at = time.monotonic()
    claim.put(1, wait=True)
    time.sleep(1.0)
    learned = [(round(t - asked_at, 4), granted) for t, granted in seen]

    claimed = attempt(m1, 2.0)

    seen.clear()
    released_at = time.monotonic()
    claim.put(0, wait=True)
    time.sleep(1.0)
    relearned = [(round(t - released_at, 4), granted) for t, granted in seen]

    released = attempt(m1, 3.0)

    m1.access_callbacks.remove(watch)
    return {
        "write_while_unclaimed": unclaimed,
        "write_while_claimed_by_other": claimed,
        "write_after_release": released,
        "access_change_seen_after_claim": learned,
        "access_change_seen_after_release": relearned,
    }


def scenario_2_what_pyepics_sees(m1: epics.PV, claim: epics.PV) -> dict[str, object]:
    """What an adapter can tell a refusal from.

    `epics_control` has to answer `Refused` here and `Broke` for a motor
    that would not move, and the two are the same call. So what is recorded
    is every channel a refusal could arrive on, including the one that
    costs nothing: asking before writing.
    """
    set_gate(claim, 1)
    asked_first = m1.write_access
    refused = attempt(m1, 42.0)

    put_no_wait: object = None
    raised_no_wait: str | None = None
    try:
        put_no_wait = m1.put(43.0, wait=False)
    except Exception as exc:
        raised_no_wait = f"{type(exc).__name__}: {exc}"
    time.sleep(SETTLE)

    caput_module_level: object = None
    raised_module: str | None = None
    try:
        caput_module_level = epics.caput(m1.pvname, 44.0, wait=True)
    except Exception as exc:
        raised_module = f"{type(exc).__name__}: {exc}"
    time.sleep(SETTLE)

    set_gate(claim, 0)
    return {
        "write_access_before_trying": asked_first,
        "put_wait_true": refused,
        "put_wait_false_returned": put_no_wait,
        "put_wait_false_raised": raised_no_wait,
        "caput_returned": caput_module_level,
        "caput_raised": raised_module,
        "value_after_all_three": m1.get(use_monitor=False),
    }


def scenario_3_granularity(
    m1: epics.PV, m2: epics.PV, free: epics.PV, claim_m1: epics.PV
) -> dict[str, object]:
    """Whether one claim decides anything about its neighbours.

    This is the property queueserver's lock does not have, and the reason
    the whole layer is worth measuring. If claiming one motor stopped
    writes to the one beside it, then this is a coarse lock with extra
    steps.
    """
    set_gate(claim_m1, 1)
    held = attempt(m1, 5.0)
    neighbour = attempt(m2, 6.0)
    ungrouped = attempt(free, 7.0)
    still_readable = {"read_access": m1.read_access, "value": m1.get(use_monitor=False)}
    set_gate(claim_m1, 0)
    return {
        "the_claimed_record": held,
        "the_record_beside_it": neighbour,
        "a_record_in_DEFAULT": ungrouped,
        "reads_of_the_claimed_record": still_readable,
    }


def scenario_4_two_processes_one_user(m2: epics.PV, claim_m2: epics.PV) -> dict[str, object]:
    """Whether a group can tell this process from another one beside it.

    m2's holder is the user running this probe, so this is the case where
    the claim is ours. The second writer is a separate interpreter, started
    here, running as the same user on the same host: exactly the rival that
    `spikes/conductor/` drove into a scan.
    """
    set_gate(claim_m2, 1)
    mine = attempt(m2, 8.0)
    rival = rival_write(m2.pvname, 9.0)
    set_gate(claim_m2, 0)
    return {
        "the_holder_writes": mine,
        "another_process_same_user_writes": rival,
        "epics_username_seen_by_the_ioc": os.environ.get("USER", "?"),
    }


def rival_write(record: str, value: float) -> dict[str, object]:
    """A write from a separate interpreter, reported as JSON on its stdout.

    A thread would share this process's CA context and therefore its
    identity, which is the thing under test. A subprocess is a genuinely
    separate client of the IOC.
    """
    script = (
        "import json, epics, sys\n"
        f"pv = epics.PV({record!r}, connection_timeout=5.0)\n"
        "pv.wait_for_connection(timeout=5.0)\n"
        "before = pv.get()\n"
        "raised = None\n"
        "returned = None\n"
        "try:\n"
        f"    returned = pv.put({value!r}, wait=True)\n"
        "except Exception as exc:\n"
        "    raised = f'{type(exc).__name__}: {exc}'\n"
        "import time; time.sleep(0.3)\n"
        "print(json.dumps({'write_access': pv.write_access, 'put_returned': returned,\n"
        "                  'raised': raised, 'value_before': before,\n"
        "                  'value_after': pv.get(use_monitor=False)}))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=False
    )
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"failed": done.stdout[-400:], "stderr": done.stderr[-400:]}


def scenario_5_trapwrite(m2: epics.PV, claim_m2: epics.PV, log: Path) -> dict[str, object]:
    """Whether TRAPWRITE on its own leaves a record of who wrote.

    Both gated rules carry the flag. If the IOC's own output says nothing
    after a trapped write, then the flag needs a listener that stock base
    does not start, and an audit trail is a second thing to install rather
    than a checkbox.
    """
    before = log.stat().st_size if log.exists() else 0
    set_gate(claim_m2, 1)
    attempt(m2, 11.0)
    set_gate(claim_m2, 0)
    time.sleep(SETTLE)
    after = log.read_text()[before:] if log.exists() else ""
    return {
        "ioc_output_grew_by_bytes": len(after),
        "ioc_said": after.strip()[:400],
    }


def reset(records: list[epics.PV], gates: list[epics.PV]) -> None:
    """Every gate down and every value at zero before anything is measured.

    A rerun otherwise inherits the last run's values, and `value_changed`
    reads false for a write that was allowed and happened to ask for the
    number already there. That is the shape of a test passing for the
    wrong reason.
    """
    for gate in gates:
        gate.put(0, wait=True)
    time.sleep(SETTLE)
    for record in records:
        record.put(0.0, wait=True)
    time.sleep(SETTLE)


def main() -> None:
    m1, m2, free = connect(M1), connect(M2), connect(FREE)
    claim_m1, claim_m2 = connect(CLAIM_M1), connect(CLAIM_M2)
    log = Path(os.environ.get("AROC_SPIKE_IOC_LOG", "ioc.log"))
    reset([m1, m2, free], [claim_m1, claim_m2])

    findings = {
        "1_the_gate": scenario_1_the_gate(m1, claim_m1),
        "2_what_pyepics_sees": scenario_2_what_pyepics_sees(m1, claim_m1),
        "3_granularity": scenario_3_granularity(m1, m2, free, claim_m1),
        "4_two_processes_one_user": scenario_4_two_processes_one_user(m2, claim_m2),
        "5_trapwrite": scenario_5_trapwrite(m2, claim_m2, log),
    }

    CAPTURE.write_text(json.dumps(findings, indent=2, default=str) + "\n")
    print(json.dumps(findings, indent=2, default=str))
    print(f"\nwritten to {CAPTURE}", file=sys.stderr)


if __name__ == "__main__":
    main()
