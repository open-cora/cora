"""Kernel-construction orchestration.

The composition root. This is the only module that decides which concrete
adapter implements which port, and it makes that decision from `Settings`
alone. Everything below it receives a `Kernel` and asks no questions about
what is inside.

Three entry points:

  - `make_inmemory_kernel`: the test-mode kernel. No pool, no network, every
    adapter in-process.
  - `make_postgres_kernel`: the production-shaped kernel over a real pool.
  - `build_kernel`: reads `Settings`, picks one of the two, and returns the
    kernel paired with a teardown.

## Why `build_kernel` takes factories rather than importing adapters

An adapter that lives inside a bounded context cannot be imported here
without making the composition root depend on that BC, and making this module
the one place every BC's import graph converges. Instead the caller passes a
factory, and `api/main.py` (which may depend on every BC) supplies it.

`authorize_factory` is the first and, today, only such seam. When a BC owns
policy evaluation, its factory is passed in here; until then the default is
`AllowAllAuthorize`, which permits every command.

## A note on defaults, for whoever adds the second factory

`AllowAllAuthorize` is a permissive default, and a production deployment that
forgot to pass a real `authorize_factory` would run with authorization off.
That is why the production-tier branch below refuses to boot rather than
falling back to it.

Copy the refusal, not just the field. A permissive default is the right shape
for a check that tests should not have to satisfy, and the wrong shape for a
deployment that silently skipped it; the two are reconciled by failing loudly
at startup, not by choosing one default and hoping.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

import asyncpg

from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.adapters.in_memory_idempotency_store import (
    InMemoryIdempotencyStore,
)
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.adapters.postgres_idempotency_store import (
    PostgresIdempotencyStore,
)
from aroc.infrastructure.adapters.read_only_event_store import ReadOnlyEventStore
from aroc.infrastructure.auth import build_idp_registry, build_static_subject_mapper
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import configure_logging
from aroc.infrastructure.pool import create_pool
from aroc.infrastructure.ports import (
    AllowAllAuthorize,
    Authorize,
    Clock,
    EventStore,
    IdempotencyStore,
    IdGenerator,
    SystemClock,
    TokenVerifier,
    UUIDv7Generator,
)
from aroc.infrastructure.schema import SchemaPosture, verify_schema_version
from aroc.infrastructure.settings import Settings

Teardown = Callable[[], Awaitable[None]]


class AuthorizeFactory(Protocol):
    """Builds the real `Authorize` from whatever the policy-owning BC needs.

    A `Protocol` with `__call__` rather than a `Callable` alias, because this
    is a construction function, which is the one case the `Authorize` port
    docstring singles out as belonging in that shape. What it replaces was
    `Callable[..., Authorize]`, which pinned the return type and left every
    argument unchecked, so a factory with the wrong signature typechecked
    here and failed at startup instead.

    `pool` is None under `app_env=test`, where the event store is in-memory.
    A factory that needs neither it nor the clock still has to name both, or
    absorb them with a catch-all: being handed an argument and ignoring it is
    a decision worth writing down.
    """

    def __call__(
        self,
        settings: Settings,
        event_store: EventStore,
        *,
        pool: asyncpg.Pool | None,
        clock: Clock,
    ) -> Authorize: ...


def make_inmemory_kernel(
    *,
    settings: Settings,
    clock: Clock,
    id_generator: IdGenerator,
    authz: Authorize,
    event_store: EventStore | None = None,
    idempotency_store: IdempotencyStore | None = None,
    token_verifier: TokenVerifier | None = None,
) -> Kernel:
    """Build a kernel with in-process adapters and no connection pool.

    The single construction site for a test-mode kernel. Tests build their
    kernel through this function rather than instantiating `Kernel` directly,
    so a field added to `Kernel` gets one default here instead of a default
    repeated across every test module. An architecture fitness test pins that
    single-site rule.
    """
    return Kernel(
        settings=settings,
        clock=clock,
        id_generator=id_generator,
        authz=authz,
        event_store=event_store if event_store is not None else InMemoryEventStore(),
        idempotency_store=(
            idempotency_store if idempotency_store is not None else InMemoryIdempotencyStore()
        ),
        pool=None,
        token_verifier=token_verifier,
    )


def make_postgres_kernel(
    pool: asyncpg.Pool,
    *,
    settings: Settings,
    clock: Clock,
    id_generator: IdGenerator,
    authz: Authorize,
    event_store: EventStore | None = None,
    idempotency_store: IdempotencyStore | None = None,
    token_verifier: TokenVerifier | None = None,
    schema_posture: SchemaPosture = "matched",
) -> Kernel:
    """Build a kernel backed by a real connection pool.

    The Postgres twin of `make_inmemory_kernel`, and the other half of the
    single-construction-site rule.
    """
    return Kernel(
        settings=settings,
        clock=clock,
        id_generator=id_generator,
        authz=authz,
        event_store=event_store if event_store is not None else PostgresEventStore(pool),
        idempotency_store=(
            idempotency_store if idempotency_store is not None else PostgresIdempotencyStore(pool)
        ),
        pool=pool,
        schema_posture=schema_posture,
        token_verifier=token_verifier,
    )


async def build_kernel(
    *,
    authorize_factory: AuthorizeFactory | None = None,
    settings: Settings | None = None,
) -> tuple[Kernel, Teardown]:
    """Construct the kernel. Called once from the FastAPI lifespan.

    `settings` is an injection point for tests that need to override
    env-loaded config. Production callers pass nothing and `Settings` reads
    from the environment and `.env` as usual.

    `token_verifier` is built from `settings.identity_providers` in BOTH
    branches, so a contract test for the bearer path can exercise verification
    end to end without Postgres. An empty provider list yields None, and the
    middleware falls through to the header path.
    """
    if settings is None:
        settings = Settings()  # pyright: ignore[reportCallIssue]  # Pydantic loads from env
    configure_logging(settings.log_level)

    clock = SystemClock()
    id_generator = UUIDv7Generator()
    idps = list(settings.identity_providers)
    token_verifier: TokenVerifier | None = build_idp_registry(
        idps,
        subject_mapper=build_static_subject_mapper(idps),
    )

    if settings.is_test:
        event_store: EventStore = InMemoryEventStore()
        authz = (
            authorize_factory(settings, event_store, pool=None, clock=clock)
            if authorize_factory is not None
            else AllowAllAuthorize()
        )
        kernel = make_inmemory_kernel(
            settings=settings,
            clock=clock,
            id_generator=id_generator,
            authz=authz,
            event_store=event_store,
            token_verifier=token_verifier,
        )
        return kernel, _noop_teardown

    if settings.is_production_tier:
        if authorize_factory is None:
            # Fail loud, not open. Falling back to AllowAllAuthorize here
            # would permit every command with nothing recording that no
            # policy was consulted, which reads as agreement rather than as
            # the absence of a gate.
            msg = (
                "build_kernel requires authorize_factory in a production-tier "
                "deployment; AllowAllAuthorize would permit every command with "
                "nothing recording that no policy was consulted"
            )
            raise ValueError(msg)
        if not settings.require_authenticated_principal:
            msg = (
                "APP_ENV is production-tier but REQUIRE_AUTHENTICATED_PRINCIPAL "
                "is false; the API would accept a client-supplied X-Principal-Id "
                "header and let any caller claim any principal"
            )
            raise ValueError(msg)

    pool = await create_pool(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )

    # Before anything can write. A mismatched schema is what a restore leaves
    # behind, and an append made against one is history rather than a row to
    # correct later. Raising here fails the lifespan, which exits the process
    # with the remedy on stderr.
    schema = await verify_schema_version(
        pool, allow_mismatch=settings.allow_schema_version_mismatch
    )
    pg_event_store: EventStore = PostgresEventStore(pool)
    if schema.posture == "degraded":
        pg_event_store = ReadOnlyEventStore(
            pg_event_store, applied=schema.applied, expected=schema.expected
        )

    authz = (
        authorize_factory(settings, pg_event_store, pool=pool, clock=clock)
        if authorize_factory is not None
        else AllowAllAuthorize()
    )

    kernel = make_postgres_kernel(
        pool,
        settings=settings,
        clock=clock,
        id_generator=id_generator,
        authz=authz,
        event_store=pg_event_store,
        token_verifier=token_verifier,
        schema_posture=schema.posture,
    )
    teardown = _make_pool_teardown(pool)
    return kernel, teardown


async def _noop_teardown() -> None:
    return None


def _make_pool_teardown(pool: asyncpg.Pool) -> Teardown:
    async def teardown() -> None:
        await pool.close()

    return teardown
