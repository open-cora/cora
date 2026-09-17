"""The decision that defining a policy produces.

Short, because the slice is. The invariants a rulebook most needs, that
it cannot be left unable to grant or unable to revoke, have nothing to
range over while a policy cannot be changed at all, and land with the
slice that makes one editable.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aroc.authority.aggregates.policy import (
    Permission,
    Policy,
    PolicyAlreadyExistsError,
    PolicyDefined,
)
from aroc.authority.features.define_policy import DefinePolicy, decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def test_defining_a_policy_emits_one_event_carrying_the_permissions() -> None:
    new_id, alice = uuid4(), uuid4()
    granted = frozenset({Permission(principal_id=alice, command_name="RegisterActor")})

    events = decide(None, DefinePolicy(permissions=granted), now=_NOW, new_id=new_id)

    assert events == [PolicyDefined(policy_id=new_id, permissions=granted, occurred_at=_NOW)]


def test_defining_a_policy_with_no_permissions_is_allowed() -> None:
    """Permitting nothing is a deliberate state while a policy is fixed."""
    events = decide(None, DefinePolicy(permissions=frozenset()), now=_NOW, new_id=uuid4())
    assert events[0].permissions == frozenset()


def test_defining_a_policy_onto_a_live_stream_is_refused() -> None:
    """The precondition is stated rather than assumed.

    A defining handler mints a fresh id, so this is unreachable through
    the ordinary path. It is here so a caller supplying its own id gets
    a refusal instead of a second genesis event on a live stream.
    """
    existing = Policy(id=uuid4(), permissions=frozenset())

    with pytest.raises(PolicyAlreadyExistsError):
        decide(existing, DefinePolicy(permissions=frozenset()), now=_NOW, new_id=uuid4())


def test_the_decider_takes_its_id_and_time_rather_than_finding_them() -> None:
    """Replay has to give the same events, so nothing may be invented.

    Called twice with the same inputs, including the same injected id
    and clock, the result is identical. A decider that reached for
    `uuid4()` or `datetime.now()` would pass every other test here and
    fail this one.
    """
    new_id, command = uuid4(), DefinePolicy(permissions=frozenset())

    first = decide(None, command, now=_NOW, new_id=new_id)
    second = decide(None, command, now=_NOW, new_id=new_id)

    assert first == second
