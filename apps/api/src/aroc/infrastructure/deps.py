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

import asyncpg

from aroc.infrastructure.adapters.canonicalization_registry import (
    CanonicalizationRegistry,
)
from aroc.infrastructure.adapters.default_canonicalizer import (
    DefaultCanonicalizer,
)
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.adapters.in_memory_idempotency_store import (
    InMemoryIdempotencyStore,
)
from aroc.infrastructure.adapters.in_memory_profile_store import InMemoryProfileStore
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.adapters.postgres_idempotency_store import (
    PostgresIdempotencyStore,
)
from aroc.infrastructure.adapters.postgres_profile_store import PostgresProfileStore
from aroc.infrastructure.adapters.signing_registry import SigningRegistry
from aroc.infrastructure.auth import build_idp_registry, build_static_subject_mapper
from aroc.infrastructure.config import Settings
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import configure_logging
from aroc.infrastructure.ports import (
    LLM,
    AllowAllAuthorize,
    Authorize,
    Clock,
    EventStore,
    IdempotencyStore,
    IdGenerator,
    LogbookMirror,
    ProfileStore,
    Signer,
    SystemClock,
    TokenVerifier,
    UUIDv7Generator,
)
from aroc.infrastructure.postgres.pool import create_pool
from aroc.infrastructure.read_only_event_store import ReadOnlyEventStore
from aroc.infrastructure.schema_version import SchemaPosture, verify_schema_version

Teardown = Callable[[], Awaitable[None]]

AuthorizeFactory = Callable[..., Authorize]
"""Builds the real `Authorize` from whatever the policy-owning BC needs.

Called with `(settings, event_store, pool=..., clock=..., id_generator=...)`.
Keyword arguments are passed by name so the factory can accept only what it
uses; a BC that gates on nothing but the event store need not take a pool.
"""

LLMFactory = Callable[[Settings], LLM]

CANONICALIZATION_V1 = "aroc/v1"
"""The deployment-wide default canonicalization version.

The version string is written into every signed envelope, so it is a
permanent wire constant. A v2 adapter registers alongside v1 rather than
replacing it: an event signed under v1 must stay verifiable under v1 forever,
which is why the registry dispatches on version rather than holding one
adapter.
"""


def _build_default_canonicalization_registry() -> CanonicalizationRegistry:
    """Return a registry with the v1 adapter registered and set as default."""
    registry = CanonicalizationRegistry()
    registry.register(CANONICALIZATION_V1, DefaultCanonicalizer())
    registry.set_default(CANONICALIZATION_V1)
    return registry


def make_inmemory_kernel(
    *,
    settings: Settings,
    clock: Clock,
    id_generator: IdGenerator,
    authz: Authorize,
    event_store: EventStore | None = None,
    idempotency_store: IdempotencyStore | None = None,
    profile_store: ProfileStore | None = None,
    token_verifier: TokenVerifier | None = None,
    signer: Signer | None = None,
    llm: LLM | None = None,
    logbook_mirror: LogbookMirror | None = None,
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
        profile_store=profile_store if profile_store is not None else InMemoryProfileStore(),
        canonicalization_registry=_build_default_canonicalization_registry(),
        signing_registry=SigningRegistry(),
        pool=None,
        token_verifier=token_verifier,
        signer=signer,
        llm=llm,
        logbook_mirror=logbook_mirror,
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
    profile_store: ProfileStore | None = None,
    token_verifier: TokenVerifier | None = None,
    signer: Signer | None = None,
    llm: LLM | None = None,
    logbook_mirror: LogbookMirror | None = None,
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
        profile_store=profile_store if profile_store is not None else PostgresProfileStore(pool),
        canonicalization_registry=_build_default_canonicalization_registry(),
        signing_registry=SigningRegistry(),
        pool=pool,
        schema_posture=schema_posture,
        token_verifier=token_verifier,
        signer=signer,
        llm=llm,
        logbook_mirror=logbook_mirror,
    )


async def build_kernel(
    *,
    authorize_factory: AuthorizeFactory | None = None,
    llm_factory: LLMFactory | None = None,
    signer_factory: Callable[[], Signer] | None = None,
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
            signer=signer_factory() if signer_factory is not None else None,
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
    llm = llm_factory(settings) if llm_factory is not None else None

    kernel = make_postgres_kernel(
        pool,
        settings=settings,
        clock=clock,
        id_generator=id_generator,
        authz=authz,
        event_store=pg_event_store,
        token_verifier=token_verifier,
        signer=signer_factory() if signer_factory is not None else None,
        llm=llm,
        schema_posture=schema.posture,
    )
    teardown = _compose_teardowns([_make_pool_teardown(pool), _maybe_llm_teardown(llm)])
    return kernel, teardown


async def _noop_teardown() -> None:
    return None


def _make_pool_teardown(pool: asyncpg.Pool) -> Teardown:
    async def teardown() -> None:
        await pool.close()

    return teardown


def _maybe_llm_teardown(llm: LLM | None) -> Teardown:
    """Build a teardown that closes the LLM client if it exposes `aclose()`.

    A production SDK client holds an httpx connection pool that must be
    released; a test double typically holds nothing. Probing for the method
    rather than requiring it on the port keeps the port free of a lifecycle
    concern only one implementor has.
    """

    async def teardown() -> None:
        if llm is None:
            return
        close = getattr(llm, "aclose", None)
        if close is None:
            return
        await close()

    return teardown


def _compose_teardowns(teardowns: list[Teardown]) -> Teardown:
    """Run teardowns sequentially, deferring the first error until all have run.

    Ordering: pass `[a, b, c]` and they run a, then b, then c at shutdown. An
    error from any one is captured and re-raised AFTER the rest have run, so a
    misbehaving client close does not leak the Postgres pool. The first
    exception wins; later ones are suppressed, per FastAPI shutdown convention.

    Catches `Exception`, NOT `BaseException`, so `asyncio.CancelledError`,
    `KeyboardInterrupt`, and `SystemExit` propagate through the chain intact.
    """

    async def composed() -> None:
        first_error: Exception | None = None
        for teardown in teardowns:
            try:
                await teardown()
            except Exception as exc:  # deferred and re-raised below
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    return composed
