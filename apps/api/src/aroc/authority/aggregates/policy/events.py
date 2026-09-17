"""Events the Policy aggregate emits, and the union its evolver dispatches on.

One event so far. A policy is authored rather than enrolled, so its
genesis is `PolicyDefined`: nothing exists anywhere until it is written,
which is the distinction the glossary draws between Defined and
Registered.

`to_payload` and `from_stored` are the single home for turning an event
into stored primitives and back.

## How a permission set is stored

In state a permission set is a `frozenset[Permission]`: deduplicated,
hashable, and O(1) to test membership, which is what the authorization
decision wants. In a payload it is a sorted list of two-element lists,
which is what JSON has and what makes two equal sets serialize
identically. Sorted, because a set has no order and an unsorted dump
would give the same policy a different payload on different runs, which
turns a stored row into something a replay cannot reproduce byte for
byte.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from aroc.authority.aggregates.policy.state import Permission
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class PolicyDefined:
    """A policy was authored, with the permissions it starts out holding.

    Carries no name and no reason. The permissions are ids and command
    names, which is what keeps this payload free of anything describing
    a person, in the one table that cannot be edited afterwards.
    """

    policy_id: UUID
    permissions: frozenset[Permission]
    occurred_at: datetime


@dataclass(frozen=True)
class PolicyPermissionGranted:
    """One permission was added to a policy.

    Carries the single pair that was added, not the resulting set. The
    set is what the fold produces; the event is what happened. Writing
    the whole set on every change would make each row a snapshot, and
    two operators granting different permissions would then overwrite
    each other instead of both landing.
    """

    policy_id: UUID
    permission: Permission
    occurred_at: datetime


PolicyEvent = PolicyDefined | PolicyPermissionGranted
"""Every event that can appear on a Policy stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def _permissions_to_payload(permissions: frozenset[Permission]) -> list[list[str]]:
    """Render a permission set as sorted pairs. See the module docstring."""
    return sorted([str(p.principal_id), p.command_name] for p in permissions)


def _permissions_from_payload(raw: Any) -> frozenset[Permission]:
    """Rebuild a permission set from stored pairs.

    Takes `Any` because it is reading a payload, which is whatever the
    row holds rather than whatever this build expects. A malformed pair
    raises `ValueError` from the unpack or from `UUID`, and the caller
    wraps that into an error naming the event.
    """
    permissions: set[Permission] = set()
    for pair in raw:
        principal_id, command_name = pair
        permissions.add(Permission(principal_id=UUID(principal_id), command_name=command_name))
    return frozenset(permissions)


def to_payload(event: PolicyEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case PolicyDefined():
            return {
                "policy_id": str(event.policy_id),
                "permissions": _permissions_to_payload(event.permissions),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case PolicyPermissionGranted():
            return {
                "policy_id": str(event.policy_id),
                "principal_id": str(event.permission.principal_id),
                "command_name": event.permission.command_name,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> PolicyEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because every constructor below raises
    it on malformed input: a string that is not a UUID, a string that is
    not a timestamp, and a permission pair that does not unpack into
    two. `TypeError` joins it because a payload whose `permissions` is
    not iterable, or holds something that is not a pair, fails that way
    rather than with a `ValueError`. Without both, either escapes as
    itself, naming the field rather than the event.
    """
    payload = stored.payload
    match stored.event_type:
        case "PolicyDefined":
            return deserialize_or_raise(
                "PolicyDefined",
                lambda: PolicyDefined(
                    policy_id=UUID(payload["policy_id"]),
                    permissions=_permissions_from_payload(payload["permissions"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError, TypeError),
            )
        case "PolicyPermissionGranted":
            return deserialize_or_raise(
                "PolicyPermissionGranted",
                lambda: PolicyPermissionGranted(
                    policy_id=UUID(payload["policy_id"]),
                    permission=Permission(
                        principal_id=UUID(payload["principal_id"]),
                        command_name=payload["command_name"],
                    ),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError, TypeError),
            )
        case unknown:
            msg = f"Unknown Policy event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "PolicyDefined",
    "PolicyEvent",
    "PolicyPermissionGranted",
    "from_stored",
    "to_payload",
]
