"""The real authorization adapter, against a policy the writes produced.

Everything else in this repository runs against `AllowAllAuthorize`,
which answers the same way whatever it is handed. This file is the only
place a denial is a decision rather than a stub's return value.

The policies here are written through the real handlers rather than
constructed, because the pair the adapter looks up has to be the pair a
grant stores. A test that built both sides in memory would agree with
itself through a serialization it never performed.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.authority.adapters import PolicyAuthorize, build_authorize
from aroc.authority.aggregates.policy import GOVERNING_COMMAND_NAMES, Permission
from aroc.authority.features.define_policy import DefinePolicy
from aroc.authority.features.define_policy import bind as bind_define
from aroc.authority.features.grant_permission import GrantPolicyPermission
from aroc.authority.features.grant_permission import bind as bind_grant
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import Allow, AllowAllAuthorize, Deny
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings
from aroc.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


def _kernel(event_store: InMemoryEventStore) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
        event_store=event_store,
    )


def _governing(principal_id: UUID) -> frozenset[Permission]:
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


async def _a_policy(deps: Kernel, administrator: UUID, *also: Permission) -> UUID:
    """Author a policy holding the governing set plus whatever else is named."""
    return await bind_define(deps)(
        DefinePolicy(permissions=_governing(administrator) | frozenset(also)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_a_pair_the_policy_holds_is_allowed() -> None:
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(_kernel(store), alice)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name=sorted(GOVERNING_COMMAND_NAMES)[0]
    )

    assert isinstance(decision, Allow)


async def test_a_pair_the_policy_does_not_hold_is_denied() -> None:
    """Deny by default: absence from the rulebook is a refusal, not a gap."""
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(_kernel(store), alice)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_right_principal_with_the_wrong_command_is_denied() -> None:
    """The pair is the unit, so holding one half permits nothing."""
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(
        _kernel(store), alice, Permission(principal_id=alice, command_name="RegisterActor")
    )

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="DeactivateActor"
    )

    assert isinstance(decision, Deny)


async def test_the_right_command_from_the_wrong_principal_is_denied() -> None:
    """The other half of the same rule, which one test cannot cover.

    A lookup keyed on the command alone passes the test above and fails
    this one; a lookup keyed on the principal alone does the reverse.
    """
    store = InMemoryEventStore()
    alice, mallory = uuid4(), uuid4()
    policy_id = await _a_policy(
        _kernel(store), alice, Permission(principal_id=alice, command_name="RegisterActor")
    )

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=mallory, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_system_principal_is_denied_everything() -> None:
    """The cost of the cutover, asserted rather than assumed.

    Under `AllowAllAuthorize` an unauthenticated request runs as the
    system principal and is permitted everything. Under this adapter it
    is permitted nothing, because it cannot hold a permission and no
    branch here makes an exception for it. A deployment that switches
    adapters without authenticating its callers stops serving.
    """
    store = InMemoryEventStore()
    policy_id = await _a_policy(_kernel(store), uuid4())

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=SYSTEM_PRINCIPAL_ID, command_name=sorted(GOVERNING_COMMAND_NAMES)[0]
    )

    assert isinstance(decision, Deny)


async def test_a_configured_policy_that_does_not_exist_denies_every_command() -> None:
    """A typo in one environment variable is an outage, never an open door."""
    store = InMemoryEventStore()
    await _a_policy(_kernel(store), uuid4())

    decision = await PolicyAuthorize(store, uuid4()).authorize(
        principal_id=uuid4(), command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)


async def test_the_denial_names_the_command_and_not_the_policy() -> None:
    """The reason reaches a caller this deployment has just refused.

    They already know which command they sent, so naming it helps. The
    policy id is deployment detail and the permissions are the map an
    unauthorized caller would most like; both stay in the log.
    """
    store = InMemoryEventStore()
    alice = uuid4()
    policy_id = await _a_policy(_kernel(store), alice)

    decision = await PolicyAuthorize(store, policy_id).authorize(
        principal_id=alice, command_name="RegisterActor"
    )

    assert isinstance(decision, Deny)
    assert "RegisterActor" in decision.reason
    assert str(policy_id) not in decision.reason
    assert str(alice) not in decision.reason


async def test_a_grant_is_visible_to_the_very_next_decision() -> None:
    """No cache, asserted so adding one has to come past this test.

    The adapter folds the policy per call, so a permission granted after
    it was constructed decides the next request. The moment that stops
    being true, a grant an operator has just made and verified will not
    take effect, and this is the test that says so.
    """
    store = InMemoryEventStore()
    deps = _kernel(store)
    alice, bob = uuid4(), uuid4()
    policy_id = await _a_policy(deps, alice)
    adapter = PolicyAuthorize(store, policy_id)
    assert isinstance(await adapter.authorize(bob, "RegisterActor"), Deny)

    await bind_grant(deps)(
        GrantPolicyPermission(
            policy_id, Permission(principal_id=bob, command_name="RegisterActor")
        ),
        principal_id=alice,
        correlation_id=uuid4(),
    )

    assert isinstance(await adapter.authorize(bob, "RegisterActor"), Allow)


def test_the_factory_hands_back_the_permissive_adapter_when_no_policy_is_configured() -> None:
    """The bootstrap posture, and the one a production tier refuses."""
    built = build_authorize(
        Settings(app_env="test"), InMemoryEventStore(), pool=None, clock=SystemClock()
    )
    assert isinstance(built, AllowAllAuthorize)


def test_the_factory_builds_the_policy_adapter_once_a_policy_is_configured() -> None:
    built = build_authorize(
        Settings(app_env="test", authz_policy_id=uuid4()),
        InMemoryEventStore(),
        pool=None,
        clock=SystemClock(),
    )
    assert isinstance(built, PolicyAuthorize)
