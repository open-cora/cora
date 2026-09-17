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

import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.authority import wire_authority
from aroc.authority.aggregates.policy import Permission, load_policy
from aroc.authority.features.define_policy import DefinePolicy
from aroc.authority.wire import AuthorityHandlers
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.deps import make_postgres_kernel
from aroc.infrastructure.ports.authorize import AllowAllAuthorize
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]


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
    granted = frozenset(
        {
            Permission(principal_id=alice, command_name="RegisterActor"),
            Permission(principal_id=alice, command_name="DefinePolicy"),
            Permission(principal_id=bob, command_name="RegisterActor"),
        }
    )

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
    granted = frozenset(
        {
            Permission(principal_id=bob, command_name="RegisterActor"),
            Permission(principal_id=alice, command_name="DefinePolicy"),
        }
    )

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


async def test_a_policy_with_no_permissions_round_trips_as_an_empty_set(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """Permitting nothing must come back as permitting nothing.

    An empty JSON array that deserialised to None, or to a missing key,
    would fold into a policy indistinguishable from one that was never
    read. It is the value a deny-all policy depends on.
    """
    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=frozenset()), principal_id=uuid4(), correlation_id=uuid4()
    )

    policy = await load_policy(PostgresEventStore(db_pool), policy_id)
    assert policy is not None
    assert policy.permissions == frozenset()


async def test_the_envelope_lands_in_columns_rather_than_in_the_payload(
    handlers: AuthorityHandlers, db_pool: asyncpg.Pool
) -> None:
    """A handler that forgot the principal writes a NULL, not a gap nobody reads."""
    caller, cid = uuid4(), uuid4()

    policy_id = await handlers.define_policy(
        DefinePolicy(permissions=frozenset()), principal_id=caller, correlation_id=cid
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
    command = DefinePolicy(permissions=frozenset())

    first: UUID = await handlers.define_policy(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )
    second: UUID = await handlers.define_policy(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key=key
    )

    assert first == second
