"""The intent: record that something outside this run stopped it."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AbortRun:
    """Mark the run with this id as having been aborted.

    Carries the id because it names a run that already exists rather than
    asking for a new one. The timestamp is still the handler's to supply
    from a port.

    Aborted is the ending where somebody or something decided to stop the
    run. The run failing on its own is the sibling command, and the two
    stay apart because the engines this system hears from tell them
    apart; collapsing them would discard a distinction the source already
    drew.

    No field says who or what did the stopping. The envelope already
    names the principal that issued this command, and anything more is a
    free-text field on a row that cannot be edited.
    """

    run_id: UUID


__all__ = ["AbortRun"]
