"""The intent: define a setup."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DefineSetup:
    """Write down a beamline's values for an operation, under a name a step can carry.

    Every field is the caller's and the id is not: the new setup id, the
    timestamp and the correlation id all come from the handler's ports, so
    the decision this command produces is reproducible on replay.

    `beamline` and `name` are plain strings here rather than the value
    objects the state holds. The decider is where they become ones, so that
    the refusal of a bad one is listed with the slice's other refusals
    instead of being raised somewhere up at the edge by whoever built the
    command.

    `settings` and `settings_schema` arrive together and are checked against each
    other. Neither means much alone: values with no description cannot be
    checked, and a description with no values names nothing a conductor
    could apply.

    **There is no `occurred_at`**, which is R8 in docs/reference/naming.md.
    Defining a setup is an act this system performs, so the moment it
    writes one is the moment it happened.
    """

    beamline: str
    operation_id: UUID
    name: str
    settings: dict[str, Any]
    settings_schema: dict[str, Any]


__all__ = ["DefineSetup"]
