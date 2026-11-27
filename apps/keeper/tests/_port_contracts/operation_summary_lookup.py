"""Behaviour every `OperationSummaryLookup` adapter owes its callers.

The run lookup's contract, for the other aggregate, and the same reason
for existing: one side reads a table a worker maintains, the other folds
every stream, and nothing about the code on one resembles the other.

Two things differ from the run contract and both are about the filter.
An operation has one transition, its retirement, and a listing leaves a
retired operation out unless it is asked for, so the two sides have to
agree on which rows a default page holds as well as on what each row
says. And a name is not unique, deliberately, so the several-matches case
is not an edge here but the one the whole slice has to get right.

A third arrived with device use. A row carries the facility's declaration
or None, and the two sides derive it differently, one from a column an
update writes and one from the fold, so they have to agree on all three
answers and on the declaration surviving a retirement.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation.state import OperationName, OperationStatus
from keeper.execution.aggregates.operation.summary import OperationSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class OperationWriter(Protocol):
    """Put operations where the adapter under test will find them."""

    async def define(self, *, operation_id: UUID, name: OperationName, at: datetime) -> None:
        """Write an operation down."""
        ...

    async def declare(self, *, operation_id: UUID, drives_devices: bool, at: datetime) -> None:
        """Declare whether a run of an operation written down earlier drives devices."""
        ...

    async def retire(self, *, operation_id: UUID, at: datetime) -> None:
        """Stop offering an operation written down earlier."""
        ...


Check = Callable[[OperationSummaryLookup, OperationWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


async def _one_operation(writer: OperationWriter, *, name: str, minute: int) -> UUID:
    operation_id = uuid4()
    await writer.define(
        operation_id=operation_id,
        name=OperationName(name),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return operation_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    _ = writer
    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_defined_plan_shows_with_its_name_and_the_time_it_was_written(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    operation_id = await _one_operation(writer, name="count", minute=0)

    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.operation_id == operation_id
    assert summary.name == OperationName("count")
    assert summary.status is OperationStatus.ACTIVE
    assert summary.created_at == _EPOCH


async def check_a_name_filter_returns_only_the_plans_called_that(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    await _one_operation(writer, name="scan", minute=0)
    wanted = await _one_operation(writer, name="count", minute=1)

    page = await lookup.list_operations(
        name=OperationName("count"), include_retired=False, limit=_PAGE, cursor=None
    )

    assert [summary.operation_id for summary in page.items] == [wanted]


async def check_a_name_filter_matching_nothing_returns_an_empty_page(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    await _one_operation(writer, name="count", minute=0)

    page = await lookup.list_operations(
        name=OperationName("absent"), include_retired=False, limit=_PAGE, cursor=None
    )

    assert page.items == []
    assert page.next_cursor is None


async def check_two_plans_sharing_a_name_both_come_back(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """The case this slice exists to be honest about. One routine
    constrained two ways is two operations, and a lookup that returned one of
    them would be choosing for the caller on the strength of an ordering
    nobody asked about."""
    first = await _one_operation(writer, name="count", minute=0)
    second = await _one_operation(writer, name="count", minute=1)

    page = await lookup.list_operations(
        name=OperationName("count"), include_retired=False, limit=_PAGE, cursor=None
    )

    assert {summary.operation_id for summary in page.items} == {first, second}


async def check_a_name_filter_is_an_exact_match_and_not_a_prefix(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """A prefix match would quietly widen every adapter's lookup, and an
    adapter resolving `count` would find `count_with_dark_frames` and run
    the wrong routine."""
    await _one_operation(writer, name="count_with_dark_frames", minute=0)

    page = await lookup.list_operations(
        name=OperationName("count"), include_retired=False, limit=_PAGE, cursor=None
    )

    assert page.items == []


async def check_plans_come_back_newest_first(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    oldest = await _one_operation(writer, name="a", minute=0)
    middle = await _one_operation(writer, name="b", minute=1)
    newest = await _one_operation(writer, name="c", minute=2)

    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)

    assert [summary.operation_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """Every operation exactly once across the pages, in one order. A boundary
    that repeated a row or dropped one would still satisfy a check that
    only counted them."""
    ids = [await _one_operation(writer, name=f"p{i}", minute=i) for i in range(5)]

    first = await lookup.list_operations(name=None, include_retired=False, limit=2, cursor=None)
    second = await lookup.list_operations(
        name=None, include_retired=False, limit=2, cursor=first.next_cursor
    )
    third = await lookup.list_operations(
        name=None, include_retired=False, limit=2, cursor=second.next_cursor
    )

    assert third.next_cursor is None
    walked = [summary.operation_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it."""
    await _one_operation(writer, name="a", minute=0)
    await _one_operation(writer, name="b", minute=1)

    page = await lookup.list_operations(name=None, include_retired=False, limit=2, cursor=None)

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """Paging and filtering compose, which matters more here than on the
    run side: several operations under one name is the ordinary case, so the
    second page of them has to stay under that name."""
    await _one_operation(writer, name="other", minute=0)
    wanted = [await _one_operation(writer, name="count", minute=i) for i in (1, 2, 3)]

    first = await lookup.list_operations(
        name=OperationName("count"), include_retired=False, limit=2, cursor=None
    )
    second = await lookup.list_operations(
        name=OperationName("count"), include_retired=False, limit=2, cursor=first.next_cursor
    )

    walked = [summary.operation_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_operations(
            name=None, include_retired=False, limit=_PAGE, cursor="not-a-cursor"
        )


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    await _one_operation(writer, name="count", minute=10)

    page = await lookup.list_operations(
        name=None,
        include_retired=False,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


async def check_a_retired_operation_is_left_out_unless_asked_for(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    kept = await _one_operation(writer, name="move", minute=0)
    retired = await _one_operation(writer, name="transfer", minute=1)
    await writer.retire(operation_id=retired, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)

    assert [summary.operation_id for summary in page.items] == [kept]


async def check_a_retired_operation_comes_back_retired_when_asked_for(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    kept = await _one_operation(writer, name="move", minute=0)
    retired = await _one_operation(writer, name="transfer", minute=1)
    await writer.retire(operation_id=retired, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_operations(name=None, include_retired=True, limit=_PAGE, cursor=None)

    assert {summary.operation_id: summary.status for summary in page.items} == {
        kept: OperationStatus.ACTIVE,
        retired: OperationStatus.RETIRED,
    }


async def check_a_retired_operation_keeps_the_time_it_was_defined(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """A list shows when a routine was written down. A side that took the
    time off the newest event would move a retired row to the top of
    every page and say it was defined when it was retired."""
    retired = await _one_operation(writer, name="transfer", minute=0)
    await writer.retire(operation_id=retired, at=_EPOCH + timedelta(minutes=30))

    page = await lookup.list_operations(name=None, include_retired=True, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.created_at == _EPOCH


async def check_retiring_the_older_of_two_under_one_name_leaves_one_under_it(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """One reason to retire an operation: a name defined twice, where the
    second should have been the only one."""
    older = await _one_operation(writer, name="tomo_scan", minute=0)
    newer = await _one_operation(writer, name="tomo_scan", minute=1)
    await writer.retire(operation_id=older, at=_EPOCH + timedelta(minutes=2))

    page = await lookup.list_operations(
        name=OperationName("tomo_scan"), include_retired=False, limit=_PAGE, cursor=None
    )

    assert [summary.operation_id for summary in page.items] == [newer]


async def check_a_default_page_counts_active_operations_alone(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """The retired rows are left out before the page is cut, not after.

    A side that cut a page of two and then dropped what was retired would
    hand back a short page, or none, while active operations were still
    waiting further down, and its cursor would skip them."""
    active: list[UUID] = []
    for minute in range(5):
        operation_id = await _one_operation(writer, name=f"p{minute}", minute=minute)
        if minute % 2:
            await writer.retire(operation_id=operation_id, at=_EPOCH + timedelta(minutes=9))
        else:
            active.append(operation_id)

    first = await lookup.list_operations(name=None, include_retired=False, limit=2, cursor=None)
    second = await lookup.list_operations(
        name=None, include_retired=False, limit=2, cursor=first.next_cursor
    )

    assert second.next_cursor is None
    walked = [summary.operation_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(active))


async def check_an_operation_nobody_declared_carries_no_device_use(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """None, and not False: undeclared is the third answer, not a quiet no."""
    await _one_operation(writer, name="count", minute=0)

    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.drives_devices is None


async def check_each_row_carries_the_declaration_made_for_it(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    """Three operations, three answers, so a side writing one value for every
    row, or the last declaration it saw, cannot pass."""
    driving = await _one_operation(writer, name="collect", minute=0)
    idle = await _one_operation(writer, name="move", minute=1)
    undeclared = await _one_operation(writer, name="count", minute=2)
    await writer.declare(operation_id=driving, drives_devices=True, at=_EPOCH + timedelta(hours=1))
    await writer.declare(operation_id=idle, drives_devices=False, at=_EPOCH + timedelta(hours=1))

    page = await lookup.list_operations(name=None, include_retired=False, limit=_PAGE, cursor=None)

    assert {summary.operation_id: summary.drives_devices for summary in page.items} == {
        driving: True,
        idle: False,
        undeclared: None,
    }


async def check_a_declaration_keeps_the_time_it_was_defined_and_survives_retirement(
    lookup: OperationSummaryLookup, writer: OperationWriter
) -> None:
    operation_id = await _one_operation(writer, name="move", minute=0)
    await writer.declare(
        operation_id=operation_id, drives_devices=False, at=_EPOCH + timedelta(minutes=10)
    )
    await writer.retire(operation_id=operation_id, at=_EPOCH + timedelta(minutes=20))

    page = await lookup.list_operations(name=None, include_retired=True, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert (summary.drives_devices, summary.status, summary.created_at) == (
        False,
        OperationStatus.RETIRED,
        _EPOCH,
    )


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_defined_plan_shows_with_its_name_and_the_time_it_was_written,
    check_a_name_filter_returns_only_the_plans_called_that,
    check_a_name_filter_matching_nothing_returns_an_empty_page,
    check_two_plans_sharing_a_name_both_come_back,
    check_a_name_filter_is_an_exact_match_and_not_a_prefix,
    check_plans_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
    check_a_retired_operation_is_left_out_unless_asked_for,
    check_a_retired_operation_comes_back_retired_when_asked_for,
    check_a_retired_operation_keeps_the_time_it_was_defined,
    check_retiring_the_older_of_two_under_one_name_leaves_one_under_it,
    check_a_default_page_counts_active_operations_alone,
    check_an_operation_nobody_declared_carries_no_device_use,
    check_each_row_carries_the_declaration_made_for_it,
    check_a_declaration_keeps_the_time_it_was_defined_and_survives_retirement,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)
