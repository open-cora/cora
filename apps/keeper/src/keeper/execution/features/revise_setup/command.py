"""The intent: write down the next revision of a setup."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ReviseSetup:
    """Replace a setup's values and their schema with a new revision of both.

    Revise, not update and not edit. The revision before this one stays on
    the stream exactly as it was written, readable by folding that far, and
    this one is numbered after it.

    `expected_revision` is the revision the caller read and is revising,
    and it is required: the values here were decided against that revision,
    so they are written only if it is still the latest.

    Both documents are whole rather than a difference, so a revision says
    everything a conductor would apply without anyone reading the revision
    before it. A caller changing one setting sends the rest unchanged.

    No beamline, no operation and no name: those are the setup's identity,
    and a setup with a different one is a different setup. The beamline the
    revision is authorized against is read off the setup's own record.

    **There is no `occurred_at`**, which is R8 in docs/reference/naming.md.
    Revising happens here, so the moment this system writes one is the
    moment it happened.
    """

    setup_id: UUID
    expected_revision: int
    settings: dict[str, Any]
    settings_schema: dict[str, Any]


__all__ = ["ReviseSetup"]
