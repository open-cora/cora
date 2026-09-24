"""A caller saying when a run's transition happened.

Three things, and they answer to different readers.

The normaliser is a pure function and is tested as one. The six handlers
are tested as a table, because "every command that reports a run honours
the reported time" is one behaviour with six instances, and a slice that
took the field and ignored it would pass every other test in the suite.
The idempotency case is here rather than next to the other retry tests
because the bug it guards against is created by this field and by nothing
else.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import RUN_STREAM_TYPE
from aroc.execution.features.abort_run import AbortRun
from aroc.execution.features.abort_run import bind as bind_abort
from aroc.execution.features.complete_run import CompleteRun
from aroc.execution.features.complete_run import bind as bind_complete
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.fail_run import FailRun
from aroc.execution.features.fail_run import bind as bind_fail
from aroc.execution.features.pause_run import PauseRun
from aroc.execution.features.pause_run import bind as bind_pause
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_report
from aroc.execution.features.resume_run import ResumeRun
from aroc.execution.features.resume_run import bind as bind_resume
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize
from aroc.infrastructure.settings import Settings
from aroc.infrastructure.slices.idempotency import hash_command
from aroc.shared.identifier import Identifier
from aroc.shared.instant import InvalidOccurredAtError, normalize_occurred_at

pytestmark = pytest.mark.unit

_CLOCK_SAYS = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
"""What the fixed clock returns, which is what a caller who says nothing gets."""

_ENGINE_SAYS = datetime(2019, 3, 4, 9, 30, tzinfo=UTC)
"""A time years before the report, which is what a backfill looks like."""

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_SAYS


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


def _kernel() -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_run(deps: Kernel, value: str = "f1e2d3c4") -> UUID:
    """A plan and a running run of it, both stamped by the clock."""
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_report(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25},
            external_ref=Identifier(scheme="bluesky-run-uid", value=value),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def test_a_naive_timestamp_is_refused() -> None:
    """No offset means no instant, only a reading off somebody's wall.

    Refused rather than assumed to be UTC, because assuming is how a row
    ends up stating a time nobody sent. Postgres would apply the session
    timezone to a naive value written into a `timestamptz` column, and
    nothing downstream could tell that had happened.
    """
    with pytest.raises(InvalidOccurredAtError):
        normalize_occurred_at(datetime(2026, 9, 18, 14, 0))


def test_an_offset_timestamp_comes_back_as_the_same_instant_in_utc() -> None:
    """Converted, not relabelled. 14:32+02:00 is 12:32Z, not 14:32Z."""
    berlin = timezone(timedelta(hours=2))
    normalized = normalize_occurred_at(datetime(2026, 9, 18, 14, 32, tzinfo=berlin))

    assert normalized == datetime(2026, 9, 18, 12, 32, tzinfo=UTC)
    assert normalized.tzinfo is UTC


def test_a_utc_timestamp_passes_through_unchanged() -> None:
    assert normalize_occurred_at(_ENGINE_SAYS) == _ENGINE_SAYS


type _Build = Callable[[UUID, datetime | None], Any]

_TRANSITIONS: tuple[tuple[str, Any, _Build, bool], ...] = (
    ("complete", bind_complete, lambda rid, at: CompleteRun(run_id=rid, occurred_at=at), False),
    ("abort", bind_abort, lambda rid, at: AbortRun(run_id=rid, occurred_at=at), False),
    ("fail", bind_fail, lambda rid, at: FailRun(run_id=rid, occurred_at=at), False),
    ("pause", bind_pause, lambda rid, at: PauseRun(run_id=rid, occurred_at=at), False),
    ("resume", bind_resume, lambda rid, at: ResumeRun(run_id=rid, occurred_at=at), True),
)
"""The five commands that move a run, how to build each, and whether it
needs a pause standing over the run first.

A table rather than five tests, because the claim is about all of them
at once. Five separate tests would pass just as well with one slice
quietly dropping the field.

Only `resume` carries the flag, because it is the one move admitted from
Paused rather than from Running. Its setup pause is stamped by the clock,
so the reported time asserted below can only have come from the command
under test.
"""

_IDS = [label for label, _b, _m, _p in _TRANSITIONS]


async def _ready_for(deps: Kernel, run_id: UUID, needs_pause: bool) -> None:
    if needs_pause:
        await bind_pause(deps)(
            PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )


@pytest.mark.parametrize(
    ("bind", "build", "needs_pause"),
    [(b, m, p) for _l, b, m, p in _TRANSITIONS],
    ids=_IDS,
)
async def test_a_transition_is_stamped_with_the_time_the_caller_reported(
    bind: Any, build: _Build, needs_pause: bool
) -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    await _ready_for(deps, run_id, needs_pause)

    await bind(deps)(build(run_id, _ENGINE_SAYS), principal_id=uuid4(), correlation_id=uuid4())

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[-1].occurred_at == _ENGINE_SAYS


@pytest.mark.parametrize(
    ("bind", "build", "needs_pause"),
    [(b, m, p) for _l, b, m, p in _TRANSITIONS],
    ids=_IDS,
)
async def test_a_transition_with_no_reported_time_falls_back_to_the_clock(
    bind: Any, build: _Build, needs_pause: bool
) -> None:
    """The other half of the table, and the one that keeps the field optional.

    A handler that always read the command would stamp `None` here, and a
    handler that always read the clock would pass the test above only if
    the two times happened to match. Running both directions is what pins
    the choice.
    """
    deps = _kernel()
    run_id = await _a_run(deps)
    await _ready_for(deps, run_id, needs_pause)

    await bind(deps)(build(run_id, None), principal_id=uuid4(), correlation_id=uuid4())

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[-1].occurred_at == _CLOCK_SAYS


async def test_a_reported_run_is_stamped_with_the_time_the_caller_reported() -> None:
    """The genesis, which takes the same field through a different shape."""
    deps = _kernel()
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    run_id = await bind_report(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25},
            external_ref=Identifier(scheme="bluesky-run-uid", value="backfilled"),
            occurred_at=_ENGINE_SAYS,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[0].occurred_at == _ENGINE_SAYS


async def test_the_recorded_time_is_the_stores_own_whatever_the_caller_claimed() -> None:
    """The claim and the write are two facts, and only one is the caller's.

    This is what makes accepting an unchecked instant safe. A report that
    names a time years in the past still carries a write time of now, so
    a reader can always see the gap rather than having to trust the
    claim.
    """
    deps = _kernel()
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    run_id = await bind_report(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25},
            external_ref=Identifier(scheme="bluesky-run-uid", value="backfilled"),
            occurred_at=_ENGINE_SAYS,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[0].occurred_at == _ENGINE_SAYS
    assert rows[0].recorded_at != _ENGINE_SAYS


def test_two_spellings_of_one_instant_hash_to_one_command() -> None:
    """The retry bug this field would create without normalising.

    `hash_command` executions the whole command through `asdict` and renders
    what it finds with `str`, so this field joins the idempotency key's
    hash the moment it exists. A caller retrying with `+00:00` where the
    first attempt sent `Z` means the same instant, and without the
    conversion in `__post_init__` the two would hash differently and the
    retry would come back 422 instead of the answer it already had.

    Asserted on the hash rather than through the wrapper, because the
    wrapper would need two full requests to show one string comparison.
    """
    run_id = uuid4()
    as_utc = CompleteRun(run_id=run_id, occurred_at=_ENGINE_SAYS)
    as_offset = CompleteRun(
        run_id=run_id, occurred_at=_ENGINE_SAYS.astimezone(timezone(timedelta(hours=2)))
    )

    assert as_utc.occurred_at == as_offset.occurred_at
    assert hash_command(as_utc) == hash_command(as_offset)
