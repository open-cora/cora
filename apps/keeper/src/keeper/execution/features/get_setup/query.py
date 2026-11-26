"""The question: what does this setup hold, now or at an earlier revision?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetSetup:
    """Read the setup with this id, at its latest revision or at the one named.

    `revision` None means the latest. A number means the setup as that
    revision left it, folded from the stream as far as that revision and no
    further, so an earlier revision reads back exactly as it was written.

    A frozen dataclass rather than bare parameters, so a query reads like
    the commands beside it and gains a field without changing every call
    site. There is no decider to hand it to: reading decides nothing.
    """

    setup_id: UUID
    revision: int | None = None


__all__ = ["GetSetup"]
