"""The Authority slices, driven end to end against a real Postgres.

Every other test of this context runs on `InMemoryEventStore`, which
hands back the very objects it was given. The permission set is the
reason that is not good enough here. In state it is a `frozenset` of
frozen dataclasses; in a row it is JSONB holding a sorted list of
two-element arrays. Nothing in memory exercises that translation, and a
policy that folds correctly from objects it never serialised proves
nothing about the one the deployed system reads back.

Two queries below spell `"Policy"` as a literal rather than using
`POLICY_STREAM_TYPE`. That is the only independent side these tests
have: a query built from the writer's own constant agrees with the
writer however wrong the constant is.

The handlers come from `wire_authority`, not from `bind`, so these go
through the same composition the application boots: tracing and the
idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.authority import wire_authority
from aroc.authority.aggregates.policy import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    PolicyCannotGrantPermissionError,
    load_policy,
)
from aroc.authority.features.define_policy import DefinePolicy
from aroc.authority.features.grant_permission import GrantPolicyPermission
from aroc.authority.wire import AuthorityHandlers
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.deps import make_postgres_kernel
from aroc.infrastructure.ports import ConcurrencyError
from aroc.infrastructure.ports.authorize import AllowAllAuthorize
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]


def _governing(principal_id: UUID) -> frozenset[Permission]:
    """The smallest permission set a policy can now be defined with.

    Derived from the aggregate's rule rather than spelled out, so a
    second governing command starts being exercised here the day it is
    added instead of the day someone remembers this file.
    """
    return frozenset(
        Permission(principal_id=principal_id, command_name=name) for name in GOVERNING_COMMAND_NAMES
    )


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> AuthorityHandlers:
    """The Authority bundle, wired exactly as the application wires it."""
    return wire_authority(
        make_postgres_kernel(
            db_pool,
            settings=Settings(app_env="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def test_a_permission_set_survives_a_round_trip_through_jsonb(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """Fold what Postgres gives back, not what was handed to the store."""
    alice, bob = uuid4(), uuid4()
    granted = _governing(alice) | {
        Permission(principal_id=alice, command_name="RegisterActor"),
        Permission(principal_id=alice, command_name="DefinePolicy"),
        Permission(principal_id=bob, command_name="RegisterActor"),
    }

    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=granted), principal_id=uuid4(), correlation_id=uuid4()
    )

    store = PostgresEventStore(db_pool)
    policy = await load_policy(store, policy_id)
    assert policy is not None
    assert policy.permissions == granted


async def test_the_stored_row_holds_sorted_pairs_under_the_pinned_stream_type(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw JSONB, so the shape is asserted and not just the fold.

    A fold that agrees with itself would pass even if the payload were
    a dict, a string, or unsorted. The stored shape is a contract with
    every future reader of this table, so it is checked directly.
    """
    alice, bob = uuid4(), uuid4()
    granted = _governing(alice) | {
        Permission(principal_id=bob, command_name="RegisterActor"),
        Permission(principal_id=alice, command_name="DefinePolicy"),
    }

    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=granted), principal_id=uuid4(), correlation_id=uuid4()
    )

    # `payload::text` rather than `payload`: the pool registers a JSONB
    # codec, so the plain column comes back already decoded. Reading the
    # text is reading what the column holds.
    row = await db_pool.fetchrow(
        "SELECT event_type, payload::text AS payload FROM events "
        "WHERE stream_type = $1 AND stream_id = $2",
        "Policy",
        policy_id,
    )
    assert row is not None
    assert row["event_type"] == "PolicyDefined"
    pairs = json.loads(row["payload"])["permissions"]
    assert pairs == sorted(pairs), "a set has no order, so the payload must impose one"
    assert pairs == sorted([[str(p.principal_id), p.command_name] for p in granted])


async def test_the_smallest_legal_policy_round_trips_intact(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """The set every bootstrap writes is the one whose round trip matters most.

    A policy can no longer be defined empty, so the smallest is the one
    naming its own administrator. If that came back short, a deployment
    would restart into a rulebook nobody could change.
    """
    minimal = _governing(uuid4())
    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=minimal), principal_id=uuid4(), correlation_id=uuid4()
    )

    policy = await load_policy(PostgresEventStore(db_pool), policy_id)
    assert policy is not None
    assert policy.permissions == minimal


async def test_the_envelope_lands_in_columns_rather_than_in_the_payload(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """A handler that forgot the principal writes a NULL, not a gap nobody reads."""
    caller, cid = uuid4(), uuid4()

    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=_governing(uuid4())),
        principal_id=caller,
        correlation_id=cid,
    )

    row = await db_pool.fetchrow(
        "SELECT principal_id, correlation_id, stream_type, payload::text AS payload "
        "FROM events WHERE stream_type = $1 AND stream_id = $2",
        "Policy",
        policy_id,
    )
    assert row is not None
    assert row["principal_id"] == caller
    assert row["correlation_id"] == cid
    assert row["stream_type"] == "Policy"
    assert "principal_id" not in json.loads(row["payload"]), (
        "who authored the policy is the envelope's; the payload names only who was granted"
    )


async def test_replaying_an_idempotency_key_returns_the_first_policy(
    handlers: AuthorityHandlers,
) -> None:
    """A retried definition must not author a second rulebook.

    This is the reason the slice carries a key at all. Two policies from
    one intent leaves a deployment authorizing against whichever id
    someone happened to write down.
    """
    caller, key = uuid4(), f"define-{uuid4()}"
    command = DefinePolicy(permissions=_governing(uuid4()))

    first: UUID = await handlers.define_policy(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )
    second: UUID = await handlers.define_policy(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )

    assert first == second


async def test_two_identical_grants_at_once_leave_one_winner(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """One intent, one event, never two. Whichever mechanism catches it.

    Both callers fold the policy at the same version and both try to
    append there. If they truly interleave, the second INSERT violates
    events_stream_version_unique and the adapter raises
    ConcurrencyError. If they serialise, the second folds a policy that
    already holds the pair and the domain refuses it. Either is correct
    and the test does not pretend to control which, because the
    interleaving is the scheduler's to decide.

    What must hold in both cases is the row count. Two operators, one
    permission, one event.
    """
    alice = uuid4()
    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=_governing(alice)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    added = Permission(principal_id=uuid4(), command_name="RegisterActor")

    results = await asyncio.gather(
        *(
            handlers.grant_permission(
                GrantPolicyPermission(policy_id, added),
                principal_id=alice,
                correlation_id=uuid4(),
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(failures[0], ConcurrencyError | PolicyCannotGrantPermissionError)

    count = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 "
        "AND event_type = 'PolicyPermissionGranted'",
        policy_id,
    )
    assert count == 1
