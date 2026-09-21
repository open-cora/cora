"""The intent: tell this system where a run's output ended up."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.shared.identifier import Identifier
from aroc.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RegisterDataset:
    """Register that a run produced this body of data, held over there.

    Register, not deposit and not write. This system did not put the data
    anywhere and could not; something else did, and this command enrols
    the result. The glossary's genesis test is the check: "register a
    dataset" sounds like filing something that came from elsewhere, and
    "define a dataset" sounds like inventing data.

    `run_id` is this system's id, which means whoever sends this has
    already resolved the engine's own uid through the run listing. That
    resolution is deliberately the caller's: it is the same lookup the
    engine reporter already makes, and doing it here would mean this
    context reaching into a sibling's read side for something the caller
    had in hand.

    `external_ref` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference. Building it
    is where a malformed scheme or value is refused, which is at the edge
    that received them.

    `occurred_at` is when the data was written, as the caller reports it,
    and a caller who omits it gets the moment the report arrived. A store
    that keeps the engine's own timestamps can supply the real one, and a
    backfill out of an archive would otherwise record every dataset as
    having appeared on the afternoon somebody ran the import.

    The dataset id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.
    """

    run_id: UUID
    external_ref: Identifier
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        The helper was Execution's when this slice was written, borrowed
        through the cross-context door. A third consumer met the rule of
        three in docs/reference/layout.md and it moved to
        `aroc.shared.instant`, so this is now an ordinary shared import
        and the door is one name narrower.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["RegisterDataset"]
