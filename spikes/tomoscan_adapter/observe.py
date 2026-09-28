"""Drive the real TomoScan lifecycle and record what a client can see.

The question this spike exists for is whether AROC's run model fits an
engine that is not Bluesky. TomoScan is the one 2-BM-S runs: EPICS, no
document stream, a scan started by putting 1 into a PV.

## What is real here and what is not

Real, imported from the installed package and not overridden: `fly_scan`,
`begin_scan`, `end_scan`, `abort_scan`, `pv_callback` and
`_end_scan_after_failure`. Those are the methods that write every status a
client can see, and the exception handling in `fly_scan` is the thing under
test. The abort below goes the way an operator's does, by putting 1 into
`AbortScan` and letting TomoScan's own callback decide what happens.

Quoted rather than driven: the two lines `TomoScan2BM.begin_scan` adds to
publish a `ScanUUID`. That class cannot be imported here at all, because it
imports `telnetlib` and Python 3.13 removed it, so the lines are carried
below and marked where they are.

Not real: the three `collect_*` methods, which drive a camera and a
rotation stage over minutes. Their stubs poll `scan_is_running` and raise
`ScanAbortError` exactly as `wait_camera_done` does, which is the line
that notices an abort. `__init__` is replaced too, because the real one
connects to about a hundred detector PVs and reads a camera manufacturer
to decide which of them exist.

So the transitions recorded are produced by TomoScan's own lines, over
real Channel Access, against a soft IOC. What is missing from them is
missing because TomoScan does not write it, not because a stub failed to.

Run it with:

    uv run --with caproto --with pyepics --with pymsgbox \\
        --with "tomoscan @ git+https://github.com/tomography/tomoscan" \\
        python spikes/tomoscan_adapter/observe.py
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")
os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")

HERE = Path(__file__).parent
OUT = HERE / "transitions.json"

SETTLE_SECONDS = 0.5
"""How long to let monitors deliver before reading what they saw."""

COLLECTING_SECONDS = 1.0
"""How long a stubbed collection runs, so an abort has somewhere to land."""


class Recorder:
    """Every monitor callback, in the order Channel Access delivered them."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def __call__(self, pvname: str = "", value: Any = None, **kw: Any) -> None:
        self.seen.append(
            {"pv": pvname.split(":")[-1], "value": value, "timestamp": kw.get("timestamp")}
        )

    def since(self, mark: int) -> list[dict[str, Any]]:
        return self.seen[mark:]


def observed(
    pvs: dict[str, Any],
    failure: type[Exception] | None,
    cleanup_fails: bool = False,
) -> Any:
    """A TomoScan whose hardware is absent and whose lifecycle is not."""
    from tomoscan.tomoscan import ScanAbortError, TomoScan

    class Observed(TomoScan):
        def __init__(self) -> None:
            self.scan_is_running = False
            self.config_pvs: dict[str, Any] = {}
            self.control_pvs: dict[str, Any] = {}
            self.pv_prefixes: dict[str, Any] = {}
            self.epics_pvs = pvs
            # The real __init__ wires this, and it is how an operator's
            # abort reaches abort_scan.
            self.epics_pvs["AbortScan"].add_callback(self.pv_callback)

        def _collect(self, status: str) -> None:
            """A stubbed collection, watching for an abort the way the real
            `wait_camera_done` does: poll `scan_is_running`, raise if it
            goes false."""
            self.epics_pvs["ScanStatus"].put(status, wait=True)
            deadline = time.time() + COLLECTING_SECONDS
            while time.time() < deadline:
                if not self.scan_is_running:
                    raise ScanAbortError
                time.sleep(0.05)

        def collect_dark_fields(self) -> None:
            self._collect("Collecting dark fields")

        def collect_flat_fields(self) -> None:
            self._collect("Collecting flat fields")

        def collect_projections(self) -> None:
            self._collect("Collecting projections")
            if failure is not None:
                raise failure

        def begin_scan(self) -> None:
            """The base class's own, then the two lines 2-BM adds after it.

            Quoted from `tomoscan_2bm.py`, not driven, for the reason the
            module docstring gives. What the quote buys is the ordering,
            which is the half a client can see: the id is published after
            the base class has already announced 'Beginning scan', so a
            subscriber that has been told a scan started still reads the
            previous scan's id for as long as that gap lasts.
            """
            super().begin_scan()
            self.epics_pvs["ScanUUID"].put(str(uuid.uuid4()), wait=True)

        def close_shutter(self) -> None:
            """Made to raise, which is how `end_scan` is made to fail.

            It stands in for any exception escaping `end_scan`, whose own
            handler names a disk-full error while writing a dataset. What
            is under test is that handler, `_end_scan_after_failure`, and
            it is the base class's own and did not exist when this spike
            first ran.
            """
            if cleanup_fails:
                raise OSError("No space left on device")
            super().close_shutter()

    return Observed()


def connect(prefix: str, recorder: Recorder, watched: tuple[str, ...]) -> dict[str, Any]:
    """Connect every PV the lifecycle uses, monitoring the interesting ones."""
    from caproto.server import pvproperty
    from epics import PV

    from ioc import TomoScanPVs

    pvs: dict[str, Any] = {}
    for name, attribute in vars(TomoScanPVs).items():
        if not isinstance(attribute, pvproperty):
            continue
        pv = PV(prefix + name, callback=recorder if name in watched else None)
        if not pv.wait_for_connection(5):
            raise RuntimeError(f"{prefix + name} never connected.")
        pvs[name] = pv

    # close_shutter reads a value PV beside the command PV, and the real
    # __init__ builds both from names the beamline configures.
    pvs["CloseShutterValue"] = pvs["OpenShutterValue"] = pvs["CamAcquireTime"]
    pvs["RotationStop"] = pvs["Rotation"]
    return pvs


def scenario(
    name: str,
    pvs: dict[str, Any],
    recorder: Recorder,
    *,
    failure: type[Exception] | None = None,
    operator_aborts: bool = False,
    clear_abort: bool = True,
    cleanup_fails: bool = False,
) -> dict[str, Any]:
    """One scan, start to finish, with whatever ended it.

    `clear_abort` exists because nothing in TomoScan puts `AbortScan` back
    to 0. Every scenario but one clears it first, which is a courtesy the
    engine does not perform for itself.

    The id is read before as well as after, because what it holds between
    scans is the question. Nothing clears that one either.
    """
    mark = len(recorder.seen)
    if clear_abort:
        pvs["AbortScan"].put(0, wait=True)
    uuid_before = pvs["ScanUUID"].get(as_string=True)
    pvs["StartScan"].put(1, wait=True)
    scan = observed(pvs, failure, cleanup_fails)

    running = threading.Thread(target=scan.fly_scan)
    running.start()
    if operator_aborts:
        time.sleep(COLLECTING_SECONDS / 2)
        pvs["AbortScan"].put(1, wait=True)
    running.join(30)
    time.sleep(SETTLE_SECONDS)

    if cleanup_fails:
        ended_by = "end_scan itself raising"
    elif operator_aborts:
        ended_by = "an operator pressing Abort"
    elif failure is not None:
        ended_by = failure.__name__
    else:
        ended_by = "nothing, it ran to the end"

    return {
        "scenario": name,
        "ended_by": ended_by,
        "transitions": recorder.since(mark),
        "scan_status_after": pvs["ScanStatus"].get(as_string=True),
        "start_scan_after": pvs["StartScan"].get(),
        "abort_scan_after": pvs["AbortScan"].get(),
        "full_file_name_after": pvs["FullFileName"].get(as_string=True),
        "scan_uuid_before": uuid_before,
        "scan_uuid_after": pvs["ScanUUID"].get(as_string=True),
    }


def main() -> None:
    from ioc import PREFIX, WATCHED, serve
    from tomoscan.tomoscan import CameraTimeoutError, FileOverwriteError

    server = multiprocessing.Process(target=serve, daemon=True)
    server.start()
    time.sleep(3)

    recorder = Recorder()
    pvs = connect(PREFIX, recorder, WATCHED)
    time.sleep(SETTLE_SECONDS)

    # Order matters for the last pair: `after_an_abort` has to follow the
    # abort directly, because it is about what the abort left behind.
    runs = [
        scenario("completes", pvs, recorder),
        scenario("camera_timeout", pvs, recorder, failure=CameraTimeoutError),
        scenario("file_overwrite", pvs, recorder, failure=FileOverwriteError),
        scenario("operator_abort", pvs, recorder, operator_aborts=True),
        scenario("after_an_abort", pvs, recorder, clear_abort=False),
        scenario("cleanup_fails", pvs, recorder, cleanup_fails=True),
    ]

    # Trailing newline so the file agrees with the repository's
    # end-of-file hook. Its sibling captures do not, and they are corrected
    # on every run of that hook and rewritten wrong by their own generator.
    OUT.write_text(json.dumps(runs, indent=2, default=str) + "\n", encoding="utf-8")
    server.terminate()
    report(runs)


def report(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        print(f"\n=== {run['scenario']}  (ended by {run['ended_by']}) ===")
        for change in run["transitions"]:
            print(f"   {change['pv']:<16} {change['value']!r}")

    print("\n=== the ending, as a client sees it ===")
    print(f"   {'scenario':<16} {'last ScanStatus':<23} {'AbortScan':<10} {'file'}")
    for run in runs:
        statuses = [c["value"] for c in run["transitions"] if c["pv"] == "ScanStatus"]
        print(
            f"   {run['scenario']:<16} {statuses[-1]!r:<23} "
            f"{run['abort_scan_after']!s:<10} {run['full_file_name_after']}"
        )

    finals = {run["scan_status_after"] for run in runs}
    print(f"\n   {len(runs)} endings, {len(finals)} distinct final status")
    for status in sorted(finals):
        sharing = [r["scenario"] for r in runs if r["scan_status_after"] == status]
        print(f"   {status!r:<23} {len(sharing)}: {', '.join(sharing)}")
    print("   the file name repeats because this IOC does not auto-increment")
    print("   FileNumber the way a real file plugin does. Not a finding.")

    print("\n=== the id, as a client sees it ===")
    print(f"   {'scenario':<16} {'ScanUUID before':<38} {'ScanUUID after'}")
    for run in runs:
        print(
            f"   {run['scenario']:<16} {run['scan_uuid_before']:<38} "
            f"{run['scan_uuid_after']}"
        )

    minted = {run["scan_uuid_after"] for run in runs}
    carried = [r["scenario"] for r in runs if r["scan_uuid_before"] == r["scan_uuid_after"]]
    print(f"\n   {len(runs)} scans, {len(minted)} distinct id")
    print(f"   {len(carried)} read their own id before starting: {carried or 'none'}")
    print("   every other scan read the previous one's, because nothing clears it")
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
