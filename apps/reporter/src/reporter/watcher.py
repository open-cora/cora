"""Run the watcher: ask the record what is unaccounted for, and account for it.

    python -m reporter.watcher --config <the reporter's own toml>

A second entrypoint beside `reporter.__main__`, and a second process.
The two do unrelated work against the same keeper: that one is handed
deliveries by an engine running beside it, this one asks services that
have been holding work since something else submitted it. One repository
with two entrypoints is cheaper than another mirror, and the alternative
is a reporter that does nothing for hours and then has to be told to go
and look.

## Why its libraries are imported here and not in `__main__`

A beamline reporter installs `--extra service` and `--extra epics` and
has never heard of Globus. `reporter.__main__` imports every adapter it
might use, so an adapter importing an SDK at its top would stop that
process from starting at a beamline that will never move a byte.

The two task adapters are imported by this module alone. A deployment
that runs the watcher installs `--extra watch`; one that does not,
does not, and nothing it runs reaches these imports.

## What a pass is

Every handover the record is still owed an account of, asked after once.
Work still going is left alone and comes round again next pass, which
for a reconstruction is most passes. A pass that finds nothing costs one
listing.

Each handover is resolved on its own. One that raises does not stop the
pass, because the far sides are independent and a service being down is
not a reason to stop accounting for work held by the other.

## What it does not do

It does not cancel anything, and it does not retry. A reference nothing
recognises is logged and left: it is either work submitted before this
was deployed, or a service this deployment was not told about, and
guessing which by acting on it would be worse than saying so.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx

from reporter.adapters.globus_compute_tasks import GlobusComputeTasks
from reporter.adapters.globus_transfer_tasks import GlobusTransferTasks
from reporter.adapters.http_keeper import HttpReporting, HttpTracking
from reporter.config import ConfigError, load
from reporter.watching import (
    AlreadyTold,
    Resolved,
    StillGoing,
    UnknownWorkError,
    across,
    resolve,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import FrameType

    from reporter.seams import Reporting
    from reporter.watching import Handover, Tracking, Watching

ORIGIN = "watcher"
"""What the record is told made these reports.

Its own word rather than the one `reporter.__main__` uses, because they
are different programs learning from different places and a record that
called them the same thing would lose which.
"""

DEFAULT_PAUSE_SECONDS = 60.0
"""How long to wait between passes when nothing says otherwise.

A minute. What this waits for is work measured in hours, so a shorter
pause spends requests to learn nothing. A pass that finds an ending a
minute late costs nothing: the record is being completed after the fact
either way.
"""

REQUEST_TIMEOUT_SECONDS = 30.0


def _stop_on_termination(stopping: list[bool]) -> None:
    """Finish the pass in hand, then stop.

    A watcher killed mid-pass loses nothing, because every report it
    makes is one the next pass would make again. Draining anyway keeps
    the log readable: a run that stops between handovers says so, and
    one cut in half looks like a crash.
    """

    def handler(_signal: int, _frame: FrameType | None) -> None:
        stopping[0] = True

    for caught in (signal.SIGTERM, signal.SIGINT):
        signal.signal(caught, handler)


def watch_once(
    tracking: Tracking,
    watching: Watching,
    reporting: Reporting,
) -> tuple[int, int]:
    """One pass. Returns how many were accounted for and how many were asked about."""
    handovers = tracking.handovers()
    accounted = 0
    for handover in handovers:
        if _account_for(watching, reporting, handover):
            accounted += 1
    return accounted, len(handovers)


def _account_for(watching: Watching, reporting: Reporting, handover: Handover) -> bool:
    """Ask after one handover, and say whether the record gained anything."""
    try:
        outcome = resolve(watching, reporting, handover, origin=ORIGIN)
    except UnknownWorkError:
        print(f"{handover.reference}: nothing asked recognises this", file=sys.stderr)
        return False
    except Exception as refused:
        print(f"{handover.reference}: {refused}", file=sys.stderr)
        return False

    match outcome:
        case Resolved(reference=reference, report=report):
            print(f"{reference}: {report}")
            return True
        case AlreadyTold() | StillGoing():
            return False
    return False


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    stopping = [False]
    _stop_on_termination(stopping)

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        client: Any = http
        tracking = HttpTracking(client, config.base_url, config.token, beamline=arguments.beamline)
        reporting = HttpReporting(client, config.base_url, config.token)
        watching = across(
            (
                GlobusTransferTasks(get_task=_transfer_tasks()),
                GlobusComputeTasks(*_compute_tasks()),
            )
        )

        print(f"accounting for work handed off at {arguments.beamline or 'every beamline'}")
        while not stopping[0]:
            try:
                accounted, asked = watch_once(tracking, watching, reporting)
            except Exception as pass_failed:
                print(f"pass failed: {pass_failed}", file=sys.stderr)
            else:
                if asked:
                    print(f"asked after {asked}, accounted for {accounted}")
            _wait(arguments.pause, stopping)

    print("stopped accounting for handed-off work", file=sys.stderr)
    return 0


def _wait(pause: float, stopping: list[bool]) -> None:
    """Sleep in slices, so a signal is noticed without waiting out the pause."""
    slept = 0.0
    while slept < pause and not stopping[0]:
        time.sleep(min(1.0, pause - slept))
        slept += 1.0


def _transfer_tasks() -> Callable[[str], Any]:
    """The one method the transfer watcher needs, bound to a built client.

    The SDK's own annotations do not survive its decorators, so the
    callable is cast to the shape the adapter asks for. The adapter
    declares that shape precisely so a deployment can hand it anything
    that answers, and this is a deployment doing that.
    """
    from alcf_tokens.auth import ServiceName, get_service_authorizer
    from globus_sdk import TransferClient

    built: Any = TransferClient(authorizer=get_service_authorizer(ServiceName("globus-transfer")))
    return cast("Callable[[str], Any]", built.get_task)


def _compute_tasks() -> tuple[Callable[[str], Any], Callable[[str], Any]]:
    """The two the compute watcher needs, for the same reason.

    The authorizer is passed rather than left to the client. One built
    without it runs its own login, which in a service blocks forever
    instead of failing, so the process never finishes starting and
    nothing says why.
    """
    from alcf_tokens.auth import ServiceName, get_service_authorizer
    from globus_compute_sdk import Client

    built: Any = Client(authorizer=get_service_authorizer(ServiceName("globus-compute")))
    return (
        cast("Callable[[str], Any]", built.get_task),
        cast("Callable[[str], Any]", built.get_result),
    )


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reporter.watcher",
        description="Finish the record of work that outlived the walk that started it.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to the reporter's toml")
    parser.add_argument(
        "--beamline",
        default=None,
        help="only this beamline's executions; every one of them when left out",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=DEFAULT_PAUSE_SECONDS,
        help="seconds between passes",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
