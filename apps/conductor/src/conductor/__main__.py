"""Run a conductor at one beamline, until somebody stops it.

    python -m conductor --config conductor.toml

One command and no subcommands. A conductor does one thing: it asks AROC
what is dispatched to its beamline, takes it up, walks it, and asks
again. There is nothing else to select.

This is the one module allowed to name an adapter, which is what the rest
of the package's layering is for. `conduct`, `intake` and everything in
`seams` speak in Protocols, so choosing Channel Access here and something
else at a Tango beamline is a change to this file rather than to any of
them.

## Why the engine is loaded by name and the control seam is not

`EpicsControl` is built from nothing: it needs a few clocks and it has
defaults for all of them, so naming the class is enough.

An acquisition seam cannot work that way. `BlueskyAcquisition` takes a
live RunEngine and a map from plan names to the callables that build
them, and a configuration file can hold neither. So the deployment writes
something that builds them and configures where it is, which is the
arrangement an IPython startup profile already has at every beamline
running bluesky.

With no such profile configured, acquisitions are refused one at a time
rather than at startup. A beamline whose procedures only move records
never reaches one, which is exactly the engineless case
`docs/reference/conducting.md` gives as the reason conducted work does
not run through an engine.

## Why a refused acquisition is reported as a break

`conduct` turns a seam that raised into `Broke`, which means the seam
raised, and that is what happened: this conductor was asked for an engine
it does not have. The alternative, refusing the whole assignment before
walking it, would leave the moves before the acquisition unwalked and the
record saying nothing about how far it got.

## Stopping

SIGTERM is made to behave like Ctrl-C, for the reason `apps/reporter`
gives: a daemon is stopped by a service manager rather than by somebody
pressing a key, and the loop checks whether to keep going between turns,
never inside a walk. So a stop lands after the procedure in progress
finishes, which can be the length of a scan. Killing a conductor harder
than that leaves the hardware wherever the last step put it, and
`spikes/conductor/FINDINGS.md` measured that a SIGKILL offers no hook to
do anything about it.
"""

from __future__ import annotations

import argparse
import importlib
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from conductor.adapters.aroc_http import HttpAroc
from conductor.adapters.epics_control import EpicsControl
from conductor.config import ConductorConfig, ConfigError, load
from conductor.intake import DEFAULT_WAIT_SECONDS, serve

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import FrameType

    from conductor.seams import Acquired, Acquisition

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long a request that is not a long poll may take before it counts as lost.

Bounded because the loop retries, and an unbounded request cannot be:
it would occupy the process until the socket gave up, which is a
conductor doing nothing at a beamline with work waiting.

The long poll passes its own timeout, above the wait it asks for, which
is why this one can be short.
"""


class NoEngineError(RuntimeError):
    """A procedure asked for a plan at a beamline with nothing to run it.

    Raised per step rather than at startup, so the moves around it still
    run and the record still says how far the procedure got.
    """


@dataclass(frozen=True, slots=True)
class NoEngine:
    """The acquisition seam of a beamline that configured none.

    An object rather than a `None` the loop checks for, so that nothing
    above here has two shapes to handle. `conduct` turns what this raises
    into `Broke`, which is an accurate account: a seam was asked and the
    seam refused.
    """

    def acquire(self, plan: str, parameters: Mapping[str, object], reference: str) -> Acquired:
        _ = parameters, reference
        raise NoEngineError(
            f"this conductor was asked to run {plan!r} and has no acquisition engine. "
            "Name one under [acquisition] in the configuration."
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Load, build, and drive. Returns a shell exit status."""
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
        acquisition = acquisition_for(config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    running = True

    def keep_going() -> bool:
        return running

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        try:
            serve(
                HttpAroc(http=http, base_url=config.base_url, token=config.token),
                config.beamline,
                control=EpicsControl(),
                acquisition=acquisition,
                wait=arguments.wait,
                keep_going=keep_going,
            )
        except KeyboardInterrupt:
            running = False
            print("\nstopping", file=sys.stderr)

    return 0


def acquisition_for(config: ConductorConfig) -> Acquisition:
    """Build the engine seam a configuration named, or one that refuses.

    The import happens at startup rather than at the first acquisition,
    so a profile that is not importable is a message before any hardware
    moves rather than a broken step in the middle of a procedure.

    What the named attribute returns is cast rather than checked.
    `Acquisition` is a Protocol, so the check that matters is structural
    and the deployment gets it from its own type checker. A runtime
    `isinstance` would confirm only that a method called `acquire`
    exists, which is the part a typo does not get wrong, and would refuse
    a perfectly good seam built by something older than this Protocol.
    """
    if config.acquisition_profile is None:
        return NoEngine()

    module_name, _, attribute = config.acquisition_profile.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as missing:
        raise ConfigError(
            f"acquisition.profile names the module {module_name!r}, which will not "
            f"import: {missing}"
        ) from missing

    build = getattr(module, attribute, None)
    if build is None:
        raise ConfigError(
            f"acquisition.profile names {attribute!r} in {module_name!r}, and there is "
            "nothing by that name there"
        )
    if not callable(build):
        raise ConfigError(
            f"acquisition.profile names {attribute!r} in {module_name!r}, which is not "
            "callable. It should be something that returns an acquisition seam."
        )

    return cast("Acquisition", build())


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="conductor",
        description="Walk whatever AROC dispatches to one beamline, as it is dispatched.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to conductor.toml")
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        metavar="SECONDS",
        help="how long one request to AROC may be held open before it answers empty",
    )
    return parser.parse_args(argv)


def stop_on_termination() -> None:
    """Make a service manager's stop signal behave like Ctrl-C.

    Ctrl-C already arrives as `KeyboardInterrupt`, so the cheapest way to
    give both signals one shutdown is to make the second arrive that way
    too. Without this, the loop's orderly stop is reachable only from a
    keyboard, which a daemon does not have.
    """

    def interrupt(number: int, frame: FrameType | None) -> None:
        _ = number, frame
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)


if __name__ == "__main__":
    stop_on_termination()
    raise SystemExit(main())
