"""The intent: tell this system that an engine ran a plan."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from aroc.execution.aggregates.run import normalize_occurred_at
from aroc.shared.identifier import Identifier


@dataclass(frozen=True)
class ReportRun:
    """Report that an engine ran this plan with these parameters.

    Report, not start. The act already happened somewhere else, and
    naming the command for what the CALLER is doing keeps the record
    from reading as a claim that this system caused it. Report rather
    than record, too: every command here records something, so the word
    would not have said which of the two ways a run can arrive this one
    is.

    `external_ref` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference. Building it
    is where a malformed scheme or value is refused, which is at the
    edge that received them, the same way a permission pair is built at
    the edge that received it.

    The run id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.

    The timestamp used to be in that list, and is not any more.
    `occurred_at` is when the engine started this run, as the caller
    reports it, and a caller who omits it gets the moment the report
    arrived. Taking it does not weaken the replay argument: the time
    moves from an ambient port onto the command, so what the decision
    depends on is if anything more tightly pinned than before. What it
    fixes is a record that said every run happened when someone got
    round to mentioning it, which for a backfill out of an engine's own
    archive was wrong by years.

    It is accepted here and not on `define_plan`, because a plan is
    authored in this system and the moment it is written IS the moment
    it exists, while a run is something that already happened somewhere
    else. See R8 in docs/reference/naming.md.
    """

    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: Identifier
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ReportRun"]
