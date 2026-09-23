"""The three walk handlers, against in-process stores.

The deciders are tested next door against states built by hand. What is
left here is what only a handler can get wrong: reading the version it
appends at, authorizing under its own command name, and writing to the
stream the command named rather than some other one.

The genuinely concurrent case is not here. Two drivers reporting one
walk at the same instant both fold the same state and both append at the
same version, and only the store's unique constraint decides between
them. That cannot be staged against an in-memory store that serialises
with a lock, so it lives in the integration tier.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.walk import (
    WALK_STREAM_TYPE,
    StepOutcome,
    WalkAlreadyEndedError,
    load_walk,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.end_walk import EndWalk
from aroc.execution.features.end_walk import bind as bind_end
from aroc.execution.features.report_step import ReportWalkStep
from aroc.execution.features.report_step import bind as bind_step
from aroc.execution.features.report_walk import ReportWalk
from aroc.execution.features.report_walk import bind as bind_report
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_STEPS = ("move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0")


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    """Refuses everything, and remembers what it was asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, surface_id)
        self.asked.append(command_name)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_walk(deps: Kernel, value: str = "walk-1") -> UUID:
    """One reported walk over the three steps above. Returns its id."""
    return await bind_report(deps)(
        ReportWalk(
            reference=Identifier(scheme="conductor", value=value),
            procedure_name="align_then_scan",
            steps=_STEPS,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_reporting_a_walk_writes_its_whole_step_list() -> None:
    deps = _kernel()

    walk_id = await _a_walk(deps)

    walk = await load_walk(deps.event_store, walk_id)
    assert walk is not None
    assert [step.describes for step in walk.steps] == list(_STEPS)
    assert walk.reference == Identifier(scheme="conductor", value="walk-1")
    assert not walk.ended


async def test_reporting_steps_one_at_a_time_lands_each_on_the_walks_stream() -> None:
    deps = _kernel()
    walk_id = await _a_walk(deps)

    await bind_step(deps)(
        ReportWalkStep(walk_id=walk_id, index=0, outcome=StepOutcome.DONE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await bind_step(deps)(
        ReportWalkStep(
            walk_id=walk_id,
            index=1,
            outcome=StepOutcome.BROKEN,
            cause="TimeoutError",
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, version = await deps.event_store.load(WALK_STREAM_TYPE, walk_id)
    assert [row.event_type for row in stored] == [
        "WalkReported",
        "WalkStepDone",
        "WalkStepBroken",
    ]
    assert version == 3


async def test_a_walk_ends_with_a_step_still_unreported() -> None:
    """The record a driver that died leaves behind, closed by something else."""
    deps = _kernel()
    walk_id = await _a_walk(deps)
    await bind_step(deps)(
        ReportWalkStep(walk_id=walk_id, index=0, outcome=StepOutcome.DONE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_end(deps)(EndWalk(walk_id=walk_id), principal_id=uuid4(), correlation_id=uuid4())

    walk = await load_walk(deps.event_store, walk_id)
    assert walk is not None
    assert walk.ended
    assert (walk.reported_count, walk.step_count) == (1, 3)


async def test_a_step_reported_after_the_ending_is_refused() -> None:
    deps = _kernel()
    walk_id = await _a_walk(deps)
    await bind_end(deps)(EndWalk(walk_id=walk_id), principal_id=uuid4(), correlation_id=uuid4())

    with pytest.raises(WalkAlreadyEndedError):
        await bind_step(deps)(
            ReportWalkStep(walk_id=walk_id, index=0, outcome=StepOutcome.DONE),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_two_walks_in_one_store_do_not_share_a_stream() -> None:
    """A step names its walk, and writing to the wrong one would still fold."""
    deps = _kernel()
    first = await _a_walk(deps, "walk-1")
    second = await _a_walk(deps, "walk-2")

    await bind_step(deps)(
        ReportWalkStep(walk_id=second, index=2, outcome=StepOutcome.SKIPPED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    untouched = await load_walk(deps.event_store, first)
    moved = await load_walk(deps.event_store, second)
    assert untouched is not None
    assert moved is not None
    assert untouched.reported_count == 0
    assert moved.steps[2].outcome is StepOutcome.SKIPPED


async def test_the_reported_timestamp_is_kept_over_the_clock() -> None:
    """A walk reported out of an archive happened when the caller says."""
    deps = _kernel()
    earlier = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)

    walk_id = await bind_report(deps)(
        ReportWalk(
            reference=Identifier(scheme="conductor", value="walk-old"),
            procedure_name="align_then_scan",
            steps=_STEPS,
            occurred_at=earlier,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(WALK_STREAM_TYPE, walk_id)
    assert stored[0].occurred_at == earlier


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("report_walk", "ReportWalk"),
        ("report_step", "ReportWalkStep"),
        ("end_walk", "EndWalk"),
    ],
)
async def test_each_handler_authorizes_under_its_own_command_name(call: str, expected: str) -> None:
    """A handler wired to a sibling's label would grant the wrong permission."""
    authz = _DenyAllAuthorize()
    deps = _kernel(authz=authz)
    walk_id = uuid4()

    with pytest.raises(UnauthorizedError):
        match call:
            case "report_walk":
                await bind_report(deps)(
                    ReportWalk(
                        reference=Identifier(scheme="conductor", value="walk-1"),
                        procedure_name="align_then_scan",
                        steps=_STEPS,
                    ),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )
            case "report_step":
                await bind_step(deps)(
                    ReportWalkStep(walk_id=walk_id, index=0, outcome=StepOutcome.DONE),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )
            case _:
                await bind_end(deps)(
                    EndWalk(walk_id=walk_id), principal_id=uuid4(), correlation_id=uuid4()
                )

    assert authz.asked == [expected]


async def test_a_denied_walk_report_writes_nothing() -> None:
    authz = _DenyAllAuthorize()
    deps = _kernel(authz=authz)

    with pytest.raises(UnauthorizedError):
        await _a_walk(deps)

    assert await deps.event_store.load(WALK_STREAM_TYPE, uuid4()) == ([], 0)
