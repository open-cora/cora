"""Turn every running pursuit, until somebody stops it.

    python -m conductor.turner --config turner.toml

A second entrypoint rather than a mode of the first. `__main__` says it
has one command and no subcommands because a conductor does one thing,
and that is still true: this does a different one. They share a
repository because the alternative was a fifth mirror in this tree for a
process that is two hundred lines, and they share nothing else. A turner
holds no claim, drives no hardware, and is not tied to a beamline.

This and `__main__` are the two modules allowed to name an adapter, which
is what the rest of the package's layering is for. `turning` speaks in a
Protocol, so reaching the record over something other than HTTP would be
a change to this file alone.

## What a pass is

Every pursuit the record will show it, each moved on by at most one step.
A pass that finds nothing to do is the normal case and costs one listing
plus one read per running pursuit.

Nothing is remembered between passes. A pursuit carries its own rounds
now, so where the loop got to is read rather than recalled, which is what
lets this be restarted, duplicated or moved without arranging anything.
Two turners racing are serialized by the record: the one that loses is
refused the round the other already opened.

## Why one failure does not stop the loop

A pursuit that refuses something is a pursuit, not a fault in the turner.
Its budget may have run out between the listing and the open, a thinker
may have answered in a way the record would not take, somebody may have
withdrawn it mid-pass. None of those is a reason to stop turning the
others, so each pursuit is attempted on its own and a refusal is logged
and passed over. What does stop the loop is a failure to reach the record
at all, because then nothing below is answerable.

## Stopping

SIGTERM is made to behave like Ctrl-C, the way `__main__` does it and for
the same reason: a daemon is stopped by a service manager rather than by
somebody pressing a key. The loop checks between passes, never inside
one. A pass is short and holds nothing, so a stop lands quickly and
leaves no round half-turned: opening and closing are each one request
that the record either took or did not.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from conductor.adapters.http_turning import HttpTurning
from conductor.config import ConfigError, TurnerConfig, load_turner
from conductor.turning import Idled, Opened, Settled, Waited, turn_once

if TYPE_CHECKING:
    from conductor.turning import Turn, Turning

TIMEOUT_SECONDS = 30.0
"""How long any one request to the record may take.

One number for every call here, because none of them waits on anything
but the record itself. The work intake needs its own because it long
polls; nothing in this does.
"""


def _say(message: str) -> None:
    print(message, flush=True)


def _report(turn: Turn) -> None:
    """Say what a pass did, in the vocabulary the record uses."""
    match turn:
        case Opened(pursuit_id=pursuit, execution_id=execution, inquiry_id=inquiry):
            _say(f"asked about {execution} for pursuit {pursuit}, as inquiry {inquiry}")
        case Settled(pursuit_id=pursuit, index=index, outcome=outcome, dispatched_id=dispatched):
            became = f", dispatching {dispatched}" if dispatched else ""
            _say(f"closed round {index} of pursuit {pursuit} as {outcome}{became}")
        case Waited(pursuit_id=pursuit, inquiry_id=inquiry):
            _say(f"pursuit {pursuit} is waiting on inquiry {inquiry}")
        case Idled():
            pass


def turn_every(turning: Turning) -> int:
    """One pass over every running pursuit. Returns how many moved."""
    moved = 0
    for pursuit in turning.pursuits():
        try:
            turn = turn_once(turning, pursuit)
        except Exception as refused:
            _say(f"pursuit {pursuit.pursuit_id} refused: {refused}")
            continue
        _report(turn)
        if not isinstance(turn, Idled | Waited):
            moved += 1
    return moved


def run(config: TurnerConfig) -> None:
    """Turn pursuits until a signal says to stop."""
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        _say("stopping after this pass")

    signal.signal(signal.SIGTERM, stop)

    with httpx.Client(timeout=TIMEOUT_SECONDS) as http:
        turning = HttpTurning(http=http, base_url=config.base_url, token=config.token)
        _say(f"turning pursuits at {config.base_url}")
        while not stopping:
            turn_every(turning)
            # Checked again before sleeping, so a stop arriving during a
            # pass does not cost a whole pause before it is honoured.
            if stopping:
                break
            time.sleep(config.pause)
    _say("stopped turning pursuits")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m conductor.turner",
        description="Turn every running pursuit the keeper will show.",
    )
    parser.add_argument("--config", type=Path, required=True, help="a turner's TOML file")
    args = parser.parse_args(argv)

    try:
        config = load_turner(args.config)
    except ConfigError as wrong:
        print(wrong, file=sys.stderr)
        return 2

    try:
        run(config)
    except KeyboardInterrupt:
        _say("stopped turning pursuits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
