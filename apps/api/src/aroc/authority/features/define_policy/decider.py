"""The decision: what defining a policy produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from aroc.authority.aggregates.policy import Policy, PolicyAlreadyExistsError, PolicyDefined
from aroc.authority.features.define_policy.command import DefinePolicy


def decide(
    state: Policy | None,
    command: DefinePolicy,
    *,
    now: datetime,
    new_id: UUID,
) -> list[PolicyDefined]:
    """Decide the events produced by defining a policy.

    Invariants:
      - State must be None, or the id already has a history
        -> PolicyAlreadyExistsError

    That is the whole of it, and the list is shorter than it will be. A
    policy cannot yet be changed after it is defined, so the two rules
    that matter most for a rulebook have nothing to range over here:
    there is no way to revoke the last permission that lets someone
    revoke, because there is no way to revoke at all. Both arrive with
    the slice that makes a policy editable, which is what creates the
    state they guard against.

    An empty permission set is accepted for the same reason. It permits
    nothing, which is a usable kill switch while a deployment switches
    policies by id, and becomes a trap only once a policy can be edited
    in place.
    """
    if state is not None:
        raise PolicyAlreadyExistsError(state.id)
    return [
        PolicyDefined(
            policy_id=new_id,
            permissions=command.permissions,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
