"""Replay Walk events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. Nothing here reads a clock,
a config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from aroc.execution.aggregates.walk.events import (
    WalkEnded,
    WalkEvent,
    WalkReported,
    WalkStepBroken,
    WalkStepDone,
    WalkStepRefused,
    WalkStepSkipped,
)
from aroc.execution.aggregates.walk.state import (
    StepOutcome,
    Walk,
    WalkProcedureName,
    WalkStep,
    validated_steps,
)
from aroc.infrastructure.slices.evolver import require_state
from aroc.shared.identifier import Identifier


def _with_outcome(state: Walk, index: int, step: WalkStep) -> Walk:
    """Return the walk with one step replaced, leaving the rest alone.

    Out-of-range indices are refused by the decider, and a row carrying
    one would mean the genesis and a later event disagree about how many
    steps there are. Folding that into a silently shorter list would hide
    a corrupt stream, so the slice assignment is left to raise.
    """
    steps = list(state.steps)
    steps[index] = step
    return replace(state, steps=tuple(steps))


def evolve(state: Walk | None, event: WalkEvent) -> Walk:
    """Apply one event to the state before it.

    The genesis arm builds the walk and ignores the prior state, which
    must be None. Every other arm goes through `require_state`: a
    transition applied to an empty stream means the log is corrupt or is
    being replayed out of order, and saying so beats folding it into a
    state that looks plausible.

    This is where a step's outcome comes from. Each arm names the outcome
    its event means, so the value on state and the event that produced it
    cannot disagree; nothing reads an outcome off a payload, because no
    payload carries one.

    Three things in the genesis arm are easy to read past. The reference
    pair goes back through `Identifier`, the procedure name back through
    its value object, and the step list back through `validated_steps`,
    so a row that no longer passes the bounds fails here rather than
    folding into a walk nothing could have written.

    The four step arms each replace exactly one element of `steps` and
    touch nothing else, which is what keeps them honest: none of them
    says anything about the walk, only about one of its steps, so the
    reference, the name and the ending come through untouched by
    construction rather than by being copied correctly four times.
    """
    match event:
        case WalkReported(
            walk_id=walk_id,
            reference_scheme=scheme,
            reference_value=value,
            procedure_name=procedure_name,
            steps=steps,
        ):
            _ = state
            return Walk(
                id=walk_id,
                reference=Identifier(scheme=scheme, value=value),
                procedure_name=WalkProcedureName(value=procedure_name),
                steps=tuple(
                    WalkStep(describes=describes) for describes in validated_steps(tuple(steps))
                ),
                ended=False,
            )
        case WalkStepDone(index=index, engine_reference=engine_reference):
            live = require_state(state, "WalkStepDone")
            return _with_outcome(
                live,
                index,
                replace(
                    live.steps[index],
                    outcome=StepOutcome.DONE,
                    engine_reference=engine_reference,
                ),
            )
        case WalkStepRefused(index=index):
            live = require_state(state, "WalkStepRefused")
            return _with_outcome(
                live,
                index,
                replace(live.steps[index], outcome=StepOutcome.REFUSED),
            )
        case WalkStepBroken(index=index, cause=cause):
            live = require_state(state, "WalkStepBroken")
            return _with_outcome(
                live,
                index,
                replace(live.steps[index], outcome=StepOutcome.BROKEN, cause=cause),
            )
        case WalkStepSkipped(index=index):
            live = require_state(state, "WalkStepSkipped")
            return _with_outcome(
                live, index, replace(live.steps[index], outcome=StepOutcome.SKIPPED)
            )
        case WalkEnded():
            return replace(require_state(state, "WalkEnded"), ended=True)
        case _:
            assert_never(event)


def fold(events: Sequence[WalkEvent]) -> Walk | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Walk | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
