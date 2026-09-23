"""The decision: what reporting one step of a walk produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

One of four events, chosen by the outcome the caller reported. That is
what puts this slice outside the command-to-event derivation check,
which covers slices emitting exactly one event.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.walk import (
    InvalidStepReportError,
    StepOutcome,
    Walk,
    WalkAlreadyEndedError,
    WalkNotFoundError,
    WalkStepAlreadyReportedError,
    WalkStepBroken,
    WalkStepDone,
    WalkStepOutOfRangeError,
    WalkStepRefused,
    WalkStepSkipped,
)
from aroc.execution.features.report_step.command import ReportWalkStep

StepEvent = WalkStepDone | WalkStepRefused | WalkStepBroken | WalkStepSkipped
"""The four events this slice can produce, one per outcome."""

_DETAIL_FIELDS: dict[StepOutcome, frozenset[str]] = {
    StepOutcome.DONE: frozenset({"engine_reference"}),
    StepOutcome.REFUSED: frozenset({"holder", "overlap"}),
    StepOutcome.BROKEN: frozenset({"cause"}),
    StepOutcome.SKIPPED: frozenset(),
}
"""Which detail fields each outcome is allowed to carry.

A table rather than four branches of ifs, because the stray-field check
is the same question asked four times and the answer is data.

Allowed, not required. Two of these fields say nothing useful when
absent and are required in their own arm below, where the message can
say what is missing: a refusal that does not name the holder and a break
that does not name what was raised are both reports a reader cannot act
on. A done step may legitimately carry no engine reference, because a
move opens no run.
"""


def _supplied(command: ReportWalkStep) -> frozenset[str]:
    """Which detail fields the caller actually filled in."""
    filled: set[str] = set()
    if command.engine_reference is not None:
        filled.add("engine_reference")
    if command.holder is not None:
        filled.add("holder")
    if command.overlap:
        filled.add("overlap")
    if command.cause is not None:
        filled.add("cause")
    return frozenset(filled)


def decide(
    state: Walk | None,
    command: ReportWalkStep,
    *,
    now: datetime,
) -> list[StepEvent]:
    """Decide the event produced by reporting one step.

    Invariants:
      - State must not be None, or no such walk was recorded
        -> WalkNotFoundError
      - The walk must not have ended
        -> WalkAlreadyEndedError
      - The index must name a step the walk holds
        -> WalkStepOutOfRangeError
      - That step must not already have an outcome
        -> WalkStepAlreadyReportedError
      - The details must belong to the outcome reported, and the two
        outcomes that cannot be read without one must carry it
        -> InvalidStepReportError

    The order matters for what a caller learns. A walk that has ended is
    refused before the index is looked at, because the walk being closed
    is the more useful fact: a caller told its index was out of range
    would go looking for an off-by-one that is not there.

    A second report for one step is refused rather than absorbed. It is
    either a repeated send, which the idempotency wrapper is there to
    catch first, or two drivers reporting one walk, which is a fault
    worth surfacing rather than resolving by whichever arrived last.

    Nothing here checks that the steps arrive in order, and the omission
    is deliberate. A driver walks sequentially, so out-of-order arrival
    would mean retries overtaking each other on the wire, and a rule
    against it would refuse a report that is perfectly true. What a
    reader needs is which steps have outcomes, which the record answers
    whatever order they landed in.

    Nothing checks the engine reference either. Whatever watches the
    engine records that run on its own schedule, so at this moment the
    run may not exist anywhere yet, and a check would refuse the common
    case. See docs/reference/conducting.md.
    """
    if state is None:
        raise WalkNotFoundError(command.walk_id)
    if state.ended:
        raise WalkAlreadyEndedError(command.walk_id)
    if not 0 <= command.index < state.step_count:
        raise WalkStepOutOfRangeError(command.walk_id, command.index, state.step_count)
    if state.steps[command.index].is_reported:
        raise WalkStepAlreadyReportedError(command.walk_id, command.index)

    stray = _supplied(command) - _DETAIL_FIELDS[command.outcome]
    if stray:
        msg = f"A step reported as {command.outcome} may not carry {', '.join(sorted(stray))}"
        raise InvalidStepReportError(msg)

    match command.outcome:
        case StepOutcome.DONE:
            return [
                WalkStepDone(
                    walk_id=command.walk_id,
                    index=command.index,
                    engine_reference=command.engine_reference,
                    occurred_at=now,
                )
            ]
        case StepOutcome.REFUSED:
            if command.holder is None:
                msg = "A refused step must name what was already holding the device"
                raise InvalidStepReportError(msg)
            return [
                WalkStepRefused(
                    walk_id=command.walk_id,
                    index=command.index,
                    holder=command.holder,
                    overlap=list(command.overlap),
                    occurred_at=now,
                )
            ]
        case StepOutcome.BROKEN:
            if command.cause is None:
                msg = "A broken step must name what was raised"
                raise InvalidStepReportError(msg)
            return [
                WalkStepBroken(
                    walk_id=command.walk_id,
                    index=command.index,
                    cause=command.cause,
                    occurred_at=now,
                )
            ]
        case StepOutcome.SKIPPED:
            return [
                WalkStepSkipped(
                    walk_id=command.walk_id,
                    index=command.index,
                    occurred_at=now,
                )
            ]


__all__ = ["StepEvent", "decide"]
