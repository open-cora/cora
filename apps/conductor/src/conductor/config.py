"""Everything a conductor has to be told, and nothing it can work out.

Three settings and an optional table: which beamline this conductor
drives, where AROC is, who this conductor is when it gets there, and
which engine, if any, it can ask to run a plan.

## Why the engine is a dotted path and not a setting

`BlueskyAcquisition` takes a live RunEngine and a map from plan names to
the callables that build them. Neither is a value a file can hold: the
engine is an object with subscriptions and state, and the plans are
Python. So what is configured is where to find something that builds
them, and the deployment writes that something.

Leaving the table out is a supported arrangement rather than a
half-configured one, which is the same call `apps/reporter` makes about
its store. A beamline whose procedures only move records has no engine to
name, and `docs/reference/conducting.md` gives that case as the reason
conducted work does not run through an engine at all. A conductor without
one drives every move and refuses every acquisition, saying so.

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
building, which is the failure `seams.Aroc` says a claim cannot be taken
back from.

## Why the beamline is not checked against a pattern

`2-bm` is the form the descriptor directory uses, and nothing here
enforces it. AROC stores a beamline as written and compares it as
written, so a conductor that insisted on a shape AROC does not would
refuse configurations AROC accepts. A name that matches no dispatch is
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
class ConductorConfig:
    """Which beamline this drives, where AROC is, who this is, and what runs plans."""

    beamline: str
    base_url: str
    token: str
    acquisition_profile: str | None = None


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
    aroc: Mapping[str, Any] = settings.get("aroc") or {}
    base_url = _required_string(aroc, "base_url", source, table_name="aroc")

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(f"{source}: aroc.base_url must be an http or https URL, got {base_url!r}")

    return ConductorConfig(
        beamline=_required_string(settings, "beamline", source, table_name=""),
        base_url=base_url.rstrip("/"),
        token=_required_string(aroc, "token", source, table_name="aroc"),
        acquisition_profile=_acquisition(settings.get("acquisition"), source),
    )


def _acquisition(table: Any, source: str) -> str | None:
    """Parse the acquisition table, or say there is none.

    A missing table switches acquisition off. A table that is present and
    wrong is an error, because the alternative is a conductor that starts,
    walks every move, and refuses the first acquisition of the day over a
    typo nobody was told about at startup.

    The separator is checked here so that the message names the format.
    An import that failed for want of a colon would say a module was not
    found, naming a string that was never a module.
    """
    if table is None:
        return None
    if not isinstance(table, Mapping):
        raise ConfigError(f"{source}: acquisition must be a table, or left out entirely")

    known: Mapping[str, Any] = cast("Mapping[str, Any]", table)
    profile = _required_string(known, "profile", source, table_name="acquisition")
    if ":" not in profile:
        raise ConfigError(
            f"{source}: acquisition.profile names a module and something in it, written "
            f"module.path:name, got {profile!r}"
        )
    return profile


def _required_string(table: Mapping[str, Any], key: str, source: str, *, table_name: str) -> str:
    named = f"{table_name}.{key}" if table_name else key
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {named} is required and must be a non-empty string")
    return value.strip()


__all__ = ["ConductorConfig", "ConfigError", "from_mapping", "load"]
