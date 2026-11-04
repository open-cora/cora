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

## Why one engine is loaded by name and the rest are not

`EpicsControl` is built from nothing but settings: a few clocks it has
defaults for, and what this deployment may write. So naming the class is
enough, and it is always in the table, because every beamline can write
a record.

An acquisition engine cannot work that way. `BlueskyEngine` takes a live
RunEngine and a map from plan names to the callables that build them,
and a configuration file can hold neither. So the deployment writes
something that builds them and configures where it is, which is the
arrangement an IPython startup profile already has at every beamline
running bluesky.

How many of those there are is the configuration's business. A procedure
that sets a record here, hands a scan to an acquisition server and then
asks somewhere else to move the file it wrote reaches three engines, and
`Repertoire` is what makes that one seam.

## Why a routine nothing runs is declined rather than broken

`Repertoire` raises `RoutineNotRunHereError` for a routine no engine
offers, and a walk reports that as `Declined`. A beamline that configured
no acquisition engine has not failed at anything when asked for a scan,
and this used to be filed as a fault, which is the reading `outcomes`
introduced `Declined` to stop. The sets around it still run either way,
because the refusal is per step rather than at startup.

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
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from conductor.adapters.epics_control import EpicsControl
from conductor.adapters.http_tasking import HttpTasking
from conductor.adapters.tomoscan_engine import TomoscanEngine
from conductor.config import (
    ConductorConfig,
    ConfigError,
    EngineChoice,
    EngineProfile,
    TomoscanServer,
    load,
)
from conductor.intake import DEFAULT_WAIT_SECONDS, serve
from conductor.procedure import SET_ROUTINE
from conductor.repertoire import Repertoire

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import FrameType

    from conductor.seams import Running

REQUEST_TIMEOUT_SECONDS = 10.0
"""How long a request that is not a long poll may take before it counts as lost.

Bounded because the loop retries, and an unbounded request cannot be:
it would occupy the process until the socket gave up, which is a
conductor doing nothing at a beamline with work waiting.

The long poll passes its own timeout, above the wait it asks for, which
is why this one can be short.
"""


def main(
    argv: Sequence[str] | None = None,
    *,
    keep_going: Callable[[], bool] = lambda: True,
) -> int:
    """Load, build, and drive. Returns a shell exit status.

    `keep_going` is what the loop asks between walks. The default never
    stops, because a caller that wants this to end is the one that knows
    when: at the entrypoint that is what `stop_on_termination` hands
    back, and in a test it is a turn count.
    """
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
        repertoire = repertoire_for(config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        try:
            serve(
                HttpTasking(http=http, base_url=config.base_url, token=config.token),
                config.beamline,
                running=repertoire,
                runs=repertoire.runs,
                wait=arguments.wait,
                keep_going=keep_going,
            )
        except KeyboardInterrupt:
            print("\nstopping", file=sys.stderr)

    return 0


def repertoire_for(config: ConductorConfig) -> Repertoire:
    """Everything this deployment can run, bound to whatever runs it.

    Channel Access is always in the table, because every beamline can
    write a record, and it is handed what this deployment may write.
    Nothing here decides what belongs in that list: it is a fact about
    where this conductor is pointed, which only the deployment knows,
    and supplying a default for it is the one thing this file must not
    do. An empty one writes nothing, which is the strictest reading
    rather than no policy at all.

    Every engine the configuration names joins it. The import happens at
    startup rather than at the first run, so a profile that will not
    import is a message before any hardware moves rather than a broken
    step in the middle of a procedure.

    Several, because work that crosses a boundary does not fit in one: a
    procedure that sets a record here, hands a scan to an acquisition
    server and then asks somewhere else to move the file it wrote needs
    three things behind one seam. `Repertoire` is that seam, and it
    refuses two engines offering one routine where the table is built,
    which is here.

    What this deployment can run and what runs it are assembled once,
    here, and the intake reads the set off the result. They used to be
    two readings of one configuration by two functions that had to match
    arm for arm, which is a shape that drifts in the worst direction: a
    conductor overstating what it runs claims work it must then refuse,
    and a claim cannot be taken back.

    What a named attribute returns is cast rather than checked.
    `Running` is a Protocol, so the check that matters is structural and
    the deployment gets it from its own type checker. A runtime
    `isinstance` would confirm only that a method called `run` exists,
    which is the part a typo does not get wrong, and would refuse a
    perfectly good seam built by something older than this Protocol.
    """
    control = (frozenset({SET_ROUTINE}), EpicsControl(writable=config.writable))
    return Repertoire.of(control, *(_offered(choice) for choice in config.engines))


def _offered(choice: EngineChoice) -> tuple[frozenset[str], Running]:
    """One configured engine, bound to the routines it was said to run."""
    match choice:
        case TomoscanServer(prefix=prefix, routines=routines, scan_timeout=bound):
            engine: Running = (
                TomoscanEngine(prefix=prefix, routines=routines)
                if bound is None
                else TomoscanEngine(prefix=prefix, routines=routines, scan_timeout=bound)
            )
        case EngineProfile(profile=profile, routines=routines):
            engine = _built_by(profile)
    return (routines, engine)


def _built_by(profile: str) -> Running:
    """Import what a deployment named, and call it.

    Split out so `repertoire_for` reads as the choice it is. What the
    named attribute returns is cast rather than checked, for the reason
    `repertoire_for` gives.
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


def stop_on_termination() -> Callable[[], bool]:
    """Ask the loop to stop when its walk ends, on Ctrl-C or on SIGTERM.

    Returns what `serve` asks between walks. A signal sets the flag and
    returns, so the walk in progress runs to its last step and reports
    it. That is the orderly stop `intake` describes and the reason its
    loop takes a predicate at all.

    Raising is what this did instead, and it reached none of that. A
    `KeyboardInterrupt` is a `BaseException`, so neither the loop's arm
    nor `conduct`'s caught one: a signal landing mid-walk unwound
    through the step that was running, which left the motor wherever
    that step had got to, the steps after it unreported, and the
    execution open at the keeper. The flag was set afterwards, around a
    `serve` that had already returned, where nothing would read it
    again. `keep_going` answered True for the whole life of every
    process that ever ran.

    Both signals, because the two want one shutdown and a daemon has no
    keyboard. The cost is that a stop asked for while the loop sits in a
    long poll waits for that poll to come back, which `--wait` bounds. A
    second signal restores the default, so an operator who will not wait
    that out sends another and the process goes at once.
    """
    stopping = False

    def keep_going() -> bool:
        return not stopping

    def ask_to_stop(number: int, frame: FrameType | None) -> None:
        nonlocal stopping
        _ = frame
        stopping = True
        signal.signal(number, signal.SIG_DFL)
        print("\nstopping when this walk ends", file=sys.stderr)

    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, ask_to_stop)

    return keep_going


if __name__ == "__main__":
    raise SystemExit(main(keep_going=stop_on_termination()))
