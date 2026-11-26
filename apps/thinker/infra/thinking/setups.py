"""The words a run names its settings by, and the one reading of them.

Shared by the profiles here that weigh what a run had, because a run of
an operation that takes a setup does not carry its own values. Its step
names a setup the record holds and may override some of it for that one
run, and what it went out with is the revision dispatch pinned it to,
with the override written over that. The ladder reads its rung there and
the gateway profile shows it to a model. Two copies of that reading
would be two answers to what one run had, free to come apart.

## Why it is read here and not in the core

`thinker.case` carries the pinned revision onto a step and leaves the
override in what the step asked for. Writing one over the other means
knowing which parameter names a setup and which overrides it, which is
reading the keeper's vocabulary for a run's parameters, and the core
leaves that to whatever reads a case. So the two words are literals
here, for the reason the words for how a step ended are literals in
`outcomes`: the keeper that defines them cannot be imported by a client
that ships as its own repository.

## Why a step pinned to nothing gives nothing

An override is written over a revision. A step that names a setup and
holds no pin, one dispatched before the record kept pins, is a run whose
values the record cannot give, and its override alone is not everything
it had. So the reading is None there, and each profile says so in its
own words rather than taking the override for the whole.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from thinker.case import Step

CONFIG: Final = "config"
"""The parameter a run names its setup by, when its operation takes one."""

OVERRIDE: Final = "override"
"""The parameter a run writes over its setup's settings with, for that run alone."""


def given(step: Step, parameters: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The values a run was given, or None where the record cannot say.

    `parameters` is what the step asked for, as the procedure declared it.
    A run that names no setup carries its values among them. One that
    names a setup was given the settings of the revision it was pinned to
    with its own override written over them, and a run pinned to no
    revision leaves nothing to write the override over.
    """
    if CONFIG not in parameters:
        return parameters
    if step.pinned is None:
        return None
    return {**step.pinned, **override(parameters)}


def override(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
    """The override a run carries, or an empty one where it carries none."""
    written = parameters.get(OVERRIDE)
    return cast("Mapping[str, Any]", written) if isinstance(written, dict) else {}


__all__ = ["CONFIG", "OVERRIDE", "given", "override"]
