"""Infrastructure ports: the `Protocol` seams every side effect goes through.

A port names a capability the domain needs without naming a technology. The
domain layer imports the Protocol; the composition root binds an adapter to
it. That inversion is what keeps deciders pure and lets the whole suite run
against in-memory implementations.

Two families live here, and only one exists today:

  - **Infrastructure seams**: `Clock`, `IdGenerator`, `EventStore`,
    `IdempotencyStore`, `Authorize`, `TokenVerifier`, `ProfileStore`.
    These are technology seams: the capability is generic and the adapter
    picks the substrate.
  - **Cross-BC lookups**: a `<Thing>Lookup` Protocol declared here,
    implemented by the owning BC's adapter, and consumed by a sibling BC
    that must not import it directly. None exist yet, because there are no
    bounded contexts.

Read that second family as a warning as much as an invitation. A lookup port
declared in this shared namespace creates a real dependency between two BCs
while leaving no import for `tach.toml` to constrain: both sides name only
`aroc.infrastructure`, which every module does. Whether such a port should
instead live in its owning BC is an open question, and the honest answer will
come from the first two BCs that need one, not from this docstring.
"""

from aroc.infrastructure.ports.authorize import (
    Allow,
    AllowAllAuthorize,
    Authorize,
    Conjunct,
    Deny,
)
from aroc.infrastructure.ports.clock import (
    Clock,
    FakeClock,
    FakeMonotonicClock,
    MonotonicClock,
    SystemClock,
    SystemMonotonicClock,
)
from aroc.infrastructure.ports.event_store import (
    ConcurrencyError,
    EventStore,
    NewEvent,
    StoredEvent,
    StreamAppend,
)
from aroc.infrastructure.ports.id_generator import (
    FixedIdGenerator,
    FixedIdGeneratorExhaustedError,
    IdGenerator,
    UUIDv7Generator,
)
from aroc.infrastructure.ports.idempotency_store import (
    CachedError,
    CachedHandlerError,
    CachedSuccess,
    Claimed,
    HashConflict,
    IdempotencyClaimLostError,
    IdempotencyConflictError,
    IdempotencyStore,
    LockedRecent,
)
from aroc.infrastructure.ports.profile_store import Profile, ProfileStore
from aroc.infrastructure.ports.token_verifier import (
    IntrospectionUnavailableError,
    InvalidTokenError,
    PrincipalKind,
    SubjectMapper,
    TokenVerifier,
    VerifiedPrincipal,
)

__all__ = [
    "Allow",
    "AllowAllAuthorize",
    "Authorize",
    "CachedError",
    "CachedHandlerError",
    "CachedSuccess",
    "Claimed",
    "Clock",
    "ConcurrencyError",
    "Conjunct",
    "Deny",
    "EventStore",
    "FakeClock",
    "FakeMonotonicClock",
    "FixedIdGenerator",
    "FixedIdGeneratorExhaustedError",
    "HashConflict",
    "IdGenerator",
    "IdempotencyClaimLostError",
    "IdempotencyConflictError",
    "IdempotencyStore",
    "IntrospectionUnavailableError",
    "InvalidTokenError",
    "LockedRecent",
    "MonotonicClock",
    "NewEvent",
    "PrincipalKind",
    "Profile",
    "ProfileStore",
    "StoredEvent",
    "StreamAppend",
    "SubjectMapper",
    "SystemClock",
    "SystemMonotonicClock",
    "TokenVerifier",
    "UUIDv7Generator",
    "VerifiedPrincipal",
]
