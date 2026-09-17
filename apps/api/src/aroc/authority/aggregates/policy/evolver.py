"""Replay Policy events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from typing import assert_never

from aroc.authority.aggregates.policy.events import PolicyDefined, PolicyEvent
from aroc.authority.aggregates.policy.state import Policy


def evolve(state: Policy | None, event: PolicyEvent) -> Policy:
    """Apply one event to the state before it.

    Only a genesis arm so far, which builds the policy and ignores the
    prior state. `require_state` is deliberately not imported yet: there
    is no transition to guard, and importing a helper against a branch
    that does not exist would read as a guard that is running.
    """
    _ = state
    match event:
        case PolicyDefined(policy_id=policy_id, permissions=permissions):
            return Policy(id=policy_id, permissions=permissions)
        case _:
            assert_never(event)


def fold(events: Sequence[PolicyEvent]) -> Policy | None:
    """Replay a stream from the empty state. None means no events at all."""
    state: Policy | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
