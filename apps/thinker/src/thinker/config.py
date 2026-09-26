"""Everything a thinker has to be told, and nothing it can work out.

Three settings: where the keeper is, who this thinker is when it gets
there, and where to find the thing that does the thinking.

## Why inference is a dotted path and not a setting

Whatever answers a case is an object with credentials, a client and state
of its own, and none of that is a value a file can hold. So what is
configured is where to find something that builds one, and the deployment
writes that something. `apps/conductor` configures its acquisition engine
the same way and for the same reason.

The consequence is that a model name, a temperature and a retry policy
appear nowhere here. They are arguments to whatever the profile builds, and
a table for them in this file would be this package holding opinions about
a provider it is written not to name.

## Why inference is required, where the conductor's engine is not

A conductor with no acquisition engine still drives every move it is given;
the engine is one of two things it can do. A thinker with no inference has
no verb at all. Making it optional would buy a process that starts, reads a
case, and then discovers it cannot do the only thing it exists for.

## Why there is no beamline

A thinker is not at one. It is handed an execution and reads the record,
and the record says which beamline the work ran at. A conductor has to be
told because it asks for work before it has any and the question would
otherwise be circular; a thinker is given the answer with the question.

## What is deliberately absent

**An objective.** It changes per invocation, which is what makes it an
argument rather than a setting. A thinker configured with a standing
objective would apply yesterday's question to today's execution without
anybody having said so.

**A choice about what to do with a conclusion.** Three of the four cannot
be written down anywhere, and the fourth always can be. There is no
behaviour here to configure until the keeper has somewhere to put the other
three.
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

    Raised at load rather than at first use, which is the call
    `apps/conductor` and `apps/reporter` both make: a process that starts on
    a malformed file and discovers it partway through has turned a typo into
    an outage, where one that refuses to start has turned it into a message.
    """


@dataclass(frozen=True)
class ThinkerConfig:
    """Where the keeper is, who this thinker is, and what forms a conclusion."""

    base_url: str
    token: str
    inference_profile: str


def load(path: Path) -> ThinkerConfig:
    """Read a configuration file, or say exactly what is wrong with it.

    TOML, because every other client in this tree reads one and a facility
    running more than one of them should not keep two formats. `tomllib` is
    in the standard library, so reading one costs this package no
    dependency, which matters here because the core has none at all.

    The token is read from the file like everything else. A deployment that
    would rather inject it another way substitutes its own loader and calls
    `from_mapping`; this is not the place to grow a second source of truth.
    """
    try:
        settings: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    return from_mapping(settings, source=str(path))


def from_mapping(settings: Mapping[str, Any], *, source: str = "configuration") -> ThinkerConfig:
    """Build a configuration from an already-parsed mapping.

    Separate from `load` so the shape can be checked without a file, and so
    a deployment holding its settings somewhere else has one function to
    call rather than a format to imitate.
    """
    keeper: Mapping[str, Any] = settings.get("keeper") or {}
    base_url = _required_string(keeper, "base_url", source, table_name="keeper")

    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"{source}: keeper.base_url must be an http or https URL, got {base_url!r}"
        )

    return ThinkerConfig(
        base_url=base_url.rstrip("/"),
        token=_required_string(keeper, "token", source, table_name="keeper"),
        inference_profile=_inference(settings.get("inference"), source),
    )


def _inference(table: Any, source: str) -> str:
    """Parse the inference table, which is not optional.

    The separator is checked here so that the message names the format. An
    import that failed for want of a colon would say a module was not found,
    naming a string that was never a module.
    """
    if table is None:
        raise ConfigError(
            f"{source}: an inference table is required, because a thinker without one "
            "cannot do the only thing it exists for"
        )
    if not isinstance(table, Mapping):
        raise ConfigError(f"{source}: inference must be a table")

    profile = _required_string(
        cast("Mapping[str, Any]", table), "profile", source, table_name="inference"
    )
    if ":" not in profile:
        raise ConfigError(
            f"{source}: inference.profile names a module and something in it, written "
            f"module.path:name, got {profile!r}"
        )
    return profile


def _required_string(table: Mapping[str, Any], key: str, source: str, *, table_name: str) -> str:
    named = f"{table_name}.{key}" if table_name else key
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {named} is required and must be a non-empty string")
    return value.strip()


__all__ = ["ConfigError", "ThinkerConfig", "from_mapping", "load"]
