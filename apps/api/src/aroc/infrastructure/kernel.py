"""Process-wide dependency kernel.

`Kernel` carries the cross-BC primitives (settings, clock, id_generator,
authorize, event_store, idempotency_store) plus the asyncpg `pool`, which is
None when `app_env=test`. It is the "shared kernel" in the DDD sense: a
deliberately-shared set of dependencies every bounded context's
`wire_<bc>(deps)` function pulls from.

## Why this lives in its own module

This module has **zero BC imports**, and that is the point. Every BC's wire,
handler, and route imports `Kernel` from here without transitively pulling in
any other BC.

Anything that needs a bounded context to construct it is INJECTED into
`build_kernel` by the composition root rather than imported here. The
authorize factory is the canonical case: the real implementation lives in
whichever BC owns policy, and a lazy import from this module would be a cycle
that a dependency checker cannot see through, because the import is
control-flow-guarded.

There are two deliberate carve-outs where a field is a concrete container
rather than a port: `canonicalization_registry` and `signing_registry`.
Version selection needs the registry container, not a single port instance.

## BC-specific stores stay BC-internal

`Kernel` carries cross-BC primitives only. A store that serves exactly one
bounded context is constructed inside that BC's own `wire_<bc>(deps)` from
`deps.pool` and lives BC-internal. This is what keeps the kernel from growing
a field per BC as the system fills in.

## What is NOT here yet

CORA's kernel carries roughly two dozen `<Thing>Lookup` fields: cross-BC read
ports, each implemented by the BC that owns the data and consumed by a
sibling. None exist here, because no bounded contexts do.

When the first one appears, note what its default says. A permissive default
(an always-satisfied lookup) keeps unrelated tests from having to seed data,
but it also means a deployment that forgot to wire the real adapter runs with
the check silently off. A `None` default that a consumer refuses to proceed
past fails loudly instead. Neither is right in general; the choice belongs to
the gate the port feeds, and it should be stated in the field's own docstring
rather than inherited by copying the field above it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg

from aroc.infrastructure.adapters.canonicalization_registry import (
    CanonicalizationRegistry,
)
from aroc.infrastructure.adapters.signing_registry import SigningRegistry
from aroc.infrastructure.ports import (
    LLM,
    Authorize,
    Clock,
    EventStore,
    IdempotencyStore,
    IdGenerator,
    ProfileStore,
    Signer,
    TokenVerifier,
)
from aroc.infrastructure.schema_version import SchemaPosture
from aroc.infrastructure.settings import Settings


@dataclass(frozen=True)
class Kernel:
    """Process-wide dependencies. Immutable after construction.

    `pool` is the asyncpg connection pool, None when `app_env=test`. A BC that
    needs an additional Postgres-backed adapter (an entry store, a projection)
    constructs it in its own `wire_<bc>(deps)` from this pool, which keeps
    BC-specific stores out of the kernel.
    """

    settings: Settings
    clock: Clock
    id_generator: IdGenerator
    authz: Authorize
    event_store: EventStore
    idempotency_store: IdempotencyStore
    profile_store: ProfileStore
    canonicalization_registry: CanonicalizationRegistry
    signing_registry: SigningRegistry

    pool: asyncpg.Pool | None = None

    schema_posture: SchemaPosture = "matched"
    """Whether the applied database schema is the one this build expects.

    `degraded` means the process booted against a mismatched schema under an
    explicit override, and its `event_store` is a `ReadOnlyEventStore`.
    Carried here so `/readyz` can report the posture: an operator who set the
    override on one host should not have to remember they did.
    """

    llm: LLM | None = None
    """The language-model port, None unless both the flag and a key are set.

    A slice that needs it types its handler as `Handler | None` and its route
    guards on None with a 503, rather than the kernel synthesizing a stub that
    would make an unwired deployment look configured.
    """

    token_verifier: TokenVerifier | None = None
    signer: Signer | None = None


AuthorizeFactory = Callable[[Kernel], Awaitable[Authorize]]
"""How the composition root supplies a real `Authorize` without an import here.

The factory receives the partially-built kernel so a policy-owning BC can
construct its adapter from `pool` and `event_store`, and returns the port.
`build_kernel` calls it once at startup. Keeping it a callable rather than an
import is what lets this module stay free of BC dependencies.
"""
