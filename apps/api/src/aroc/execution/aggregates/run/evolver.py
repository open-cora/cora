"""Replay Run events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from typing import assert_never

from aroc.execution.aggregates.run.events import RunEvent, RunReported
from aroc.execution.aggregates.run.state import Run
from aroc.shared.identifier import Identifier


def evolve(state: Run | None, event: RunEvent) -> Run:
    """Apply one event to the state before it.

    The genesis arm builds the run and ignores the prior state, which
    must be None.

    Two things happen on the way through that are easy to read past. The
    reference pair goes back through `Identifier`, so a row whose scheme
    or value no longer passes the bounds fails here rather than folding
    into a run whose reference nothing could have written. And the
    parameters are shallow-copied, so the dict on the state and the dict
    in the payload that built it are not the same object.
    """
    match event:
        case RunReported(
            run_id=run_id,
            plan_id=plan_id,
            parameters=parameters,
            external_ref_scheme=scheme,
            external_ref_value=value,
        ):
            _ = state
            return Run(
                id=run_id,
                plan_id=plan_id,
                parameters=dict(parameters),
                external_ref=Identifier(scheme=scheme, value=value),
            )
        case _:
            assert_never(event)


def fold(events: Sequence[RunEvent]) -> Run | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Run | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
