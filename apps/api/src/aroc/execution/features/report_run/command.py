"""The intent: tell this system that an engine ran a plan."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

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

    The run id, the timestamp and the correlation id are not the
    caller's. They come from the handler's ports, so the decision this
    command produces is reproducible on replay.
    """

    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: Identifier


__all__ = ["ReportRun"]
