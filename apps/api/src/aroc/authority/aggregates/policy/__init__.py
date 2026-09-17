"""The Policy aggregate: state, events, the fold, and how to load one."""

from aroc.authority.aggregates.policy.events import (
    PolicyDefined,
    PolicyEvent,
    from_stored,
    to_payload,
)
from aroc.authority.aggregates.policy.evolver import evolve, fold
from aroc.authority.aggregates.policy.read import (
    POLICY_STREAM_TYPE,
    load_policy,
    load_policy_with_version,
)
from aroc.authority.aggregates.policy.state import (
    Permission,
    Policy,
    PolicyAlreadyExistsError,
    PolicyNotFoundError,
)

__all__ = [
    "POLICY_STREAM_TYPE",
    "Permission",
    "Policy",
    "PolicyAlreadyExistsError",
    "PolicyDefined",
    "PolicyEvent",
    "PolicyNotFoundError",
    "evolve",
    "fold",
    "from_stored",
    "load_policy",
    "load_policy_with_version",
    "to_payload",
]
