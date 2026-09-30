"""Everything a conductor has to be told, and nothing it can work out.

Three settings and an optional table: which beamline this conductor
drives, where the keeper is, who this conductor is when it gets there, and
which engine, if any, it can ask to run a routine.

## Why an engine is sometimes a dotted path and sometimes two settings

`BlueskyEngine` takes a live RunEngine and a map from plan names to
the callables that build them. Neither is a value a file can hold: the
engine is an object with subscriptions and state, and the plans are
Python. So what is configured is where to find something that builds
them, and the deployment writes that something.

`TomoscanEngine` takes a record prefix and a set of routine names, and
both are strings. Sending a beamline off to author a Python file for two
strings would put untested code at every station running TomoScan, which
is four of them here, to say what a file says perfectly well. So the run
table has a second shape and the deployment writes no code at all.

The rule behind the two, for whatever engine comes next: a profile is for
an engine whose settings are not values. Anything a file can hold belongs
in the file.

Leaving the table out is a supported arrangement rather than a
half-configured one, which is the same call `apps/reporter` makes about
its store. A beamline whose procedures only set records has no engine to
name, and `docs/conducting.md` gives that case as the reason conducted
work does not run through an engine at all. A conductor without one
drives every set and refuses every run, saying so.

A table that is present and names neither shape is refused rather than
read as none, because writing one is asking for an engine.

## Why the beamline is configured and not derived

It is the one fact that cannot come from anywhere else. A conductor could
in principle read it off the records its procedures name, but it has to
know the beamline before it asks for a procedure, which is what makes the
question circular.

Deriving it from the token was the other candidate and is worse. A filter
is a question anybody may ask and a credential is who you are, so binding
the two would mean an operator could not ask what another beamline is
waiting on without holding that beamline's identity. It would also make
one wrong grant into a conductor driving hardware at the wrong end of the
building, which is the failure `seams.Tasking.take` says a claim cannot be
taken back from.

## Why the beamline is not checked against a pattern

`2-bm` is the form the descriptor directory uses, and nothing here
enforces it. The keeper stores a beamline as written and compares it as
written, so a conductor that insisted on a shape the keeper does not would
refuse configurations the keeper accepts. A name that matches no dispatch is
already visible as a conductor that never finds work.

## What is deliberately absent

**How long a long poll may block.** A bound on the socket rather than a
fact about the beamline, so it lives beside the loop that chooses it. A
deployment behind a proxy that closes idle connections earlier finds out
loudly, because the request fails rather than returning empty.

**The control adapter's clocks.** `EpicsControl` carries defaults for its
timeout, its settle and its tolerance. They are worth configuring the day
a beamline needs different ones, and a table for them today would be
three settings with one possible value each.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path


class ConfigError(ValueError):
    """The configuration cannot be used, with the reason a person can fix.

    Raised at load rather than at first use, which is the same choice
    `apps/reporter` makes and for the same reason: a conductor that
    starts on a malformed file and discovers it on the first dispatch of
    the day has turned a typo into an outage, where one that refuses to
    start has turned it into a message.
    """


@dataclass(frozen=True)
class EngineProfile:
    """An engine a deployment builds, named by where to find the builder."""

    profile: str


@dataclass(frozen=True)
class TomoscanServer:
    """A TomoScan server at an address, which a deployment need not build.

    Everything this engine takes is a string, so it is written in the
    file rather than in a Python file a beamline would otherwise have to
    author and nothing would test. Naming the kind here is not the core
    knowing an adapter: no module above `adapters/` imports one, and
    `__main__` is still where the object is made.
    """

    prefix: str
    routines: frozenset[str]


EngineChoice = EngineProfile | TomoscanServer
"""What a run table can name. Which one is decided by the key present."""


@dataclass(frozen=True)
class ConductorConfig:
    """Which beamline this drives, where the keeper is, who this is, and what runs a routine."""

    beamline: str
    base_url: str
    token: str
    engine: EngineChoice | None = None


def load(path: Path) -> ConductorConfig:
    """Read a configuration file, or say exactly what is wrong with it.

    TOML, because `apps/reporter` reads one and a beamline running both
    should not keep two formats. `tomllib` is in the standard library, so
    reading one costs this package no dependency, which matters more here
    than next door: every module above `adapters/` imports nothing else.

    The token is read from the file like everything else. A deployment
    that would rather inject it another way substitutes its own loader
    and calls `from_mapping`; this is not the place to grow a second
    source of truth.
    """
    try:
        settings: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    return from_mapping(settings, source=str(path))


def from_mapping(settings: Mapping[str, Any], *, source: str = "configuration") -> ConductorConfig:
    """Build a configuration from an already-parsed mapping.

    Separate from `load` so the shape can be checked without a file, and
    so a deployment holding its settings somewhere else has one function
    to call rather than a format to imitate.
    """
    keeper: Mapping[str, Any] = settings.get("keeper") or {}
    base_url = _required_string(keeper, "base_url", source, table_name="keeper")

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"{source}: keeper.base_url must be an http or https URL, got {base_url!r}"
        )

    return ConductorConfig(
        beamline=_required_string(settings, "beamline", source, table_name=""),
        base_url=base_url.rstrip("/"),
        token=_required_string(keeper, "token", source, table_name="keeper"),
        engine=_engine(settings.get("run"), source),
    )


def _engine(table: Any, source: str) -> EngineChoice | None:
    """Parse the run table, or say there is none.

    A missing table switches run off. A table that is present and wrong
    is an error, because the alternative is a conductor that starts,
    walks every set, and refuses the first run of the day over a typo
    nobody was told about at startup.

    Which of the two shapes is meant is decided by the key present rather
    than by a tag naming it. A table carrying both names two engines and
    is refused, and one carrying neither is refused with both spelled
    out, so neither mistake reaches a beamline as a guess.
    """
    if table is None:
        return None
    if not isinstance(table, Mapping):
        raise ConfigError(f"{source}: run must be a table, or left out entirely")

    known: Mapping[str, Any] = cast("Mapping[str, Any]", table)
    names_profile = "profile" in known
    names_prefix = "prefix" in known

    if names_profile and names_prefix:
        raise ConfigError(
            f"{source}: run names both profile and prefix, and it is one or the "
            "other. profile is for an engine the deployment builds; prefix is for "
            "a TomoScan server this can talk to without any."
        )
    if names_profile:
        profile = _required_string(known, "profile", source, table_name="run")
        if ":" not in profile:
            raise ConfigError(
                f"{source}: run.profile names a module and something in it, written "
                f"module.path:name, got {profile!r}"
            )
        return EngineProfile(profile)
    if names_prefix:
        return TomoscanServer(
            prefix=_required_string(known, "prefix", source, table_name="run"),
            routines=_routines(known.get("routines"), source),
        )
    raise ConfigError(
        f"{source}: run must name either profile, for an engine the deployment "
        "builds, or prefix, for a TomoScan server. Leave the table out entirely "
        "for a conductor that only sets records."
    )


def _routines(value: Any, source: str) -> frozenset[str]:
    """The routine names a TomoScan server will answer to.

    Required and non-empty, because the engine refuses a routine it was
    not told about and a server configured to answer to nothing would
    refuse every run while looking configured.
    """
    if not isinstance(value, list):
        raise ConfigError(f"{source}: run.routines is required and must be a list of names")
    named: list[Any] = cast("list[Any]", value)
    routines = {entry.strip() for entry in named if isinstance(entry, str) and entry.strip()}
    if len(routines) != len(named) or not routines:
        raise ConfigError(
            f"{source}: run.routines must be a non-empty list of non-empty names, got {named!r}"
        )
    return frozenset(routines)


def _required_string(table: Mapping[str, Any], key: str, source: str, *, table_name: str) -> str:
    named = f"{table_name}.{key}" if table_name else key
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {named} is required and must be a non-empty string")
    return value.strip()


__all__ = [
    "ConductorConfig",
    "ConfigError",
    "EngineChoice",
    "EngineProfile",
    "TomoscanServer",
    "from_mapping",
    "load",
]
