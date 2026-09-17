"""The registration handler, against in-process stores.

The handler is the only place the two-store write happens, so these
assertions are about what ends up where. The one worth reading is
`test_a_failing_profile_write_still_leaves_the_actor_registered`, which
pins the write ORDER by making the second write fail and checking the
first one survived. Swap the two statements in the handler and it fails.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.access.aggregates.actor import ACTOR_STREAM_TYPE, Actor, load_actor
from aroc.access.errors import UnauthorizedError
from aroc.access.features.register_actor import RegisterActor, bind
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.adapters.in_memory_profile_store import InMemoryProfileStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny, Profile
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.request import NIL_SENTINEL_ID
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingIdGenerator:
    """Hands out predictable ids so a test can name the one it expects."""

    def __init__(self) -> None:
        self.issued: list[UUID] = []

    def new_id(self) -> UUID:
        minted = uuid4()
        self.issued.append(minted)
        return minted


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        conduit_id: UUID,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, conduit_id, surface_id)
        return Deny(reason="not on the list")


class _RefusingProfileStore(InMemoryProfileStore):
    """A vault whose write always fails, standing in for a crash mid-request."""

    async def upsert(self, *, actor_id: UUID, name: str, created_at: datetime) -> None:
        _ = (actor_id, name, created_at)
        msg = "the vault is unreachable"
        raise RuntimeError(msg)


def _kernel(
    *,
    authz: object | None = None,
    profile_store: object | None = None,
    event_store: InMemoryEventStore | None = None,
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_CountingIdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
        profile_store=profile_store or InMemoryProfileStore(),  # pyright: ignore[reportArgumentType]
    )


async def test_registering_returns_the_id_the_actor_can_be_loaded_by() -> None:
    deps = _kernel()
    handler = bind(deps, profile_store=deps.profile_store)

    actor_id = await handler(
        RegisterActor(name="Ada Lovelace"), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_actor(deps.event_store, actor_id) == Actor(id=actor_id)


async def test_registering_writes_the_display_name_to_the_vault() -> None:
    deps = _kernel()
    handler = bind(deps, profile_store=deps.profile_store)

    actor_id = await handler(
        RegisterActor(name="Ada Lovelace"), principal_id=uuid4(), correlation_id=uuid4()
    )

    stored = await deps.profile_store.get(actor_id)
    assert stored == Profile(
        actor_id=actor_id, name="Ada Lovelace", created_at=_WHEN, updated_at=_WHEN
    )


async def test_registering_trims_the_name_on_its_way_to_the_vault() -> None:
    deps = _kernel()
    handler = bind(deps, profile_store=deps.profile_store)

    actor_id = await handler(
        RegisterActor(name="  Ada Lovelace  "), principal_id=uuid4(), correlation_id=uuid4()
    )

    stored = await deps.profile_store.get(actor_id)
    assert stored is not None
    assert stored.name == "Ada Lovelace"


async def test_the_appended_event_carries_no_trace_of_the_name() -> None:
    """The two-box boundary, checked on what actually reached the store."""
    deps = _kernel()
    handler = bind(deps, profile_store=deps.profile_store)

    actor_id = await handler(
        RegisterActor(name="Ada Lovelace"), principal_id=uuid4(), correlation_id=uuid4()
    )

    rows, _version = await deps.event_store.load(ACTOR_STREAM_TYPE, actor_id)
    assert "Ada" not in str(rows[0].payload)
    assert "Ada" not in str(rows[0].metadata)


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    handler = bind(deps, profile_store=deps.profile_store)
    caller = uuid4()

    actor_id = await handler(
        RegisterActor(name="Ada Lovelace"), principal_id=caller, correlation_id=uuid4()
    )

    rows, _version = await deps.event_store.load(ACTOR_STREAM_TYPE, actor_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    handler = bind(deps, profile_store=deps.profile_store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await handler(
            RegisterActor(name="Ada Lovelace"), principal_id=uuid4(), correlation_id=uuid4()
        )

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    assert generator.issued == [], "authorization must be decided before an id is minted"


async def test_a_failing_profile_write_still_leaves_the_actor_registered() -> None:
    """The write order, pinned by the failure it was chosen for.

    The event goes first so that a crash between the two writes leaves a
    nameless actor rather than a profile row holding a person's name under
    an id no event references. Swap the two statements in the handler and
    this fails: nothing would be registered, and the vault would hold the
    name instead.
    """
    store = InMemoryEventStore()
    deps = _kernel(profile_store=_RefusingProfileStore(), event_store=store)
    handler = bind(deps, profile_store=deps.profile_store)

    with pytest.raises(RuntimeError, match="the vault is unreachable"):
        await handler(
            RegisterActor(name="Ada Lovelace"), principal_id=uuid4(), correlation_id=uuid4()
        )

    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    actor_id = generator.issued[0]
    assert await load_actor(store, actor_id) == Actor(id=actor_id), (
        "the event should already be durable when the vault write fails"
    )
    assert await deps.profile_store.get(actor_id) is None
