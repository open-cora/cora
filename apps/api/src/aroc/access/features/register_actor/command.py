"""The intent: register an actor under this display name."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RegisterActor:
    """Register a new actor with the given display name.

    Carries only what the caller controls. The new id, the timestamp and
    the correlation id are the handler's to supply from ports, so that
    the decision made from this command is reproducible on replay.
    """

    name: str


__all__ = ["RegisterActor"]
