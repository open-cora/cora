"""Run a conductor at one beamline, until somebody stops it.

    python -m conductor --config conductor.toml

One command and no subcommands. A conductor does one thing: it asks the keeper
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

An engine seam cannot work that way. `BlueskyEngine` takes a
live RunEngine and a map from plan names to the callables that build
them, and a configuration file can hold neither. So the deployment writes
something that builds them and configures where it is, which is the
arrangement an IPython startup profile already has at every beamline
running bluesky.

With no such profile configured, runs are refused one at a time
rather than at startup. A beamline whose procedures only set records
never reaches one, which is exactly the engineless case
`docs/conducting.md` gives as the reason conducted work does not run
through an engine.

## Why a refused run is reported as a break

`conduct` turns a seam that raised into `Broke`, which means the seam
raised, and that is what happened: this conductor was asked for an engine
it does not have. The alternative, refusing the whole assignment before
walking it, would leave the sets before the run unwalked and the
record saying nothing about how far it got.

## Stopping

SIGTERM is made to behave like Ctrl-C, for the reason `apps/reporter`
gives: a daemon is stopped by a service manager rather than by somebody
pressing a key, and the loop checks whether to keep going between turns,
never inside a walk. So a stop lands after the procedure in progress
finishes, which can be the length of a scan. Killing a conductor harder
than that leaves the hardware wherever the last step put it, and SIGKILL
offers no hook to do anything about it.
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

from conductor.adapters.epics_control import EpicsControl
from conductor.adapters.http_tasking import HttpTasking
from conductor.adapters.tomoscan_engine import TomoscanEngine
from conductor.config import ConductorConfig, ConfigError, EngineProfile, TomoscanServer, load
from conductor.confinement import Confinement
from conductor.intake import DEFAULT_WAIT_SECONDS, serve

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import FrameType

    from conductor.seams import Adjusting, Citation, Ran, Running

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long a request that is not a long poll may take before it counts as lost.

Bounded because the loop retries, and an unbounded request cannot be:
it would occupy the process until the socket gave up, which is a
conductor doing nothing at a beamline with work waiting.

The long poll passes its own timeout, above the wait it asks for, which
is why this one can be short.
"""


class NoEngineError(RuntimeError):
    """A procedure asked for a routine at a beamline with nothing to run it.

    Raised per step rather than at startup, so the sets around it still
    run and the record still says how far the procedure got.
    """


@dataclass(frozen=True, slots=True)
class NoEngine:
    """The engine seam of a beamline that configured none.

    An object rather than a `None` the loop checks for, so that nothing
    above here has two shapes to handle. `conduct` turns what this raises
    into `Broke`, which is an accurate account: a seam was asked and the
    seam refused.
    """

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        _ = parameters, cites
        raise NoEngineError(
            f"this conductor was asked to run {routine!r} and has no engine. "
            "Name one under [run] in the configuration."
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Load, build, and drive. Returns a shell exit status."""
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
        engine = engine_for(config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    serving = True

    def keep_going() -> bool:
        return serving

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        try:
            serve(
                HttpTasking(http=http, base_url=config.base_url, token=config.token),
                config.beamline,
                adjusting=control_for(config),
                running=engine,
                wait=arguments.wait,
                keep_going=keep_going,
            )
        except KeyboardInterrupt:
            serving = False
            print("\nstopping", file=sys.stderr)

    return 0


def control_for(config: ConductorConfig) -> Adjusting:
    """The control seam, held to the records this deployment may set.

    Always wrapped, including where nothing is writable. A conductor that
    dropped the wrapper when it had no scopes would treat an empty
    configuration as no policy rather than as the strictest one, which is
    the reading `confinement` exists to refuse.

    Nothing here decides what belongs in the list. That is a fact about
    where this conductor is pointed, which only the deployment knows, and
    the one thing this file must not do is supply a default for it.
    """
    return Confinement(adjusting=EpicsControl(), writable=config.writable)


def engine_for(config: ConductorConfig) -> Running:
    """Build the engine seam a configuration named, or one that refuses.

    The import happens at startup rather than at the first run,
    so a profile that is not importable is a message before any hardware
    moves rather than a broken step in the middle of a procedure.

    What the named attribute returns is cast rather than checked.
    `Running` is a Protocol, so the check that matters is structural
    and the deployment gets it from its own type checker. A runtime
    `isinstance` would confirm only that a method called `run`
    exists, which is the part a typo does not get wrong, and would refuse
    a perfectly good seam built by something older than this Protocol.
    """
    match config.engine:
        case None:
            return NoEngine()
        case TomoscanServer(prefix=prefix, routines=routines):
            return TomoscanEngine(prefix=prefix, routines=routines)
        case EngineProfile(profile=profile):
            return _built_by(profile)


def _built_by(profile: str) -> Running:
    """Import what a deployment named, and call it.

    Split out so `engine_for` reads as the choice it is. What the named
    attribute returns is cast rather than checked, for the reason
    `engine_for` gives.
    """
    module_name, _, attribute = profile.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as missing:
        raise ConfigError(
            f"run.profile names the module {module_name!r}, which will not import: {missing}"
        ) from missing

    build = getattr(module, attribute, None)
    if build is None:
        raise ConfigError(
            f"run.profile names {attribute!r} in {module_name!r}, and there is "
            "nothing by that name there"
        )
    if not callable(build):
        raise ConfigError(
            f"run.profile names {attribute!r} in {module_name!r}, which is not "
            "callable. It should be something that returns an engine seam."
        )

    return cast("Running", build())


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="conductor",
        description="Walk whatever the keeper dispatches to one beamline, as it is dispatched.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to conductor.toml")
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        metavar="SECONDS",
        help="how long one request to the keeper may be held open before it answers empty",
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
