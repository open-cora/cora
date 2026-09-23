"""The intent: tell this system that something walked a procedure."""

from dataclasses import dataclass
from datetime import datetime

from aroc.shared.identifier import Identifier
from aroc.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ReportWalk:
    """Report that something began walking this procedure, over these steps.

    Report, not start, and the word is load-bearing in the same way it is
    on `ReportRun`. The act already began somewhere else, and a command
    named for what this system did would claim it drove something it did
    not. When this system does drive one, that is a different command
    with its own genesis event, the way a driving surface for runs is
    reserved beside the reporting one.

    `reference` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference. It is what
    whatever drove the walk calls it, minted before the first step ran
    because there is no handle at that moment.

    `steps` is the whole list, in order, and it is not optional. A walk
    reporting its steps one at a time leaves a reader of a walk that
    stopped reporting unable to tell one that finished early from one
    that was abandoned, and the list is the only thing that closes that.
    It is also fixed here for good: no later command adds to it.

    The walk id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.

    `occurred_at` is when the walk began, as the caller reports it, and a
    caller who omits it gets the moment the report arrived. Accepted for
    the reason `ReportRun` accepts one and `define_plan` does not: a walk
    is something that happened somewhere else. See R8 in
    docs/reference/naming.md.
    """

    reference: Identifier
    procedure_name: str
    steps: tuple[str, ...]
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ReportWalk"]
