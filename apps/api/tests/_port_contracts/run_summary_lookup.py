"""Behaviour every `RunSummaryLookup` adapter owes its callers.

The third contract in this package and the one with the widest gap between
its two implementations. The others differ in mechanism: a dict against
SQL, doing the same thing two ways. These differ in kind. One reads a
table a background worker maintains; the other folds every run stream on
every call because there is no table to read. Nothing about the code on
one side resembles the code on the other, so nothing but this file makes
"they answer alike" a checkable claim.

Both drivers write through real run events rather than seeding rows, so
the Postgres side exercises the projection as well as the query. That is
deliberate: a contract that inserted rows directly would agree on reading
and say nothing about whether the two sides agree on what a run event
means.

The one thing this cannot compare is lag. The projection is eventually
consistent and the fold is immediate, so the Postgres driver drains before
it reads. Whether a caller can read too soon is a real question and it
belongs where the worker runs, not here.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run.state import RunStatus
from aroc.execution.aggregates.run.summary import RunSummaryLookup
from aroc.infrastructure.projection.cursor import InvalidCursorError, encode_cursor
from aroc.shared.identifier import Identifier


class RunWriter(Protocol):
    """Put runs where the adapter under test will find them.

    Two verbs, because two are enough to reach every column: a genesis
    sets everything and one ending moves the status and the second
    timestamp. The five transitions are the evolver's business and are
    tested there.
    """

    async def report(
        self,
        *,
        run_id: UUID,
        plan_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        """Record a run as started."""
        ...

    async def complete(self, *, run_id: UUID, at: datetime) -> None:
        """Record that the run reached its own end."""
        ...


Check = Callable[[RunSummaryLookup, RunWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from.

Fixed rather than `now`, so an ordering assertion reads as an ordering
rather than as arithmetic on the wall clock, and so a failure prints the
same timestamps every run.
"""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""


def _ref(value: str) -> Identifier:
    return Identifier(scheme="bluesky-run-uid", value=value)


async def _one_run(writer: RunWriter, *, value: str, minute: int) -> UUID:
    run_id = uuid4()
    await writer.report(
        run_id=run_id,
        plan_id=uuid4(),
        external_ref=_ref(value),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return run_id


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    _ = writer
    page = await lookup.list_runs(external_ref=None, limit=_PAGE, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


async def check_a_reported_run_shows_as_running_at_the_time_it_was_reported(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    run_id = await _one_run(writer, value="a", minute=0)

    page = await lookup.list_runs(external_ref=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.run_id == run_id
    assert summary.external_ref == _ref("a")
    assert summary.status is RunStatus.RUNNING
    assert summary.created_at == _EPOCH
    assert summary.updated_at == _EPOCH


async def check_an_ending_moves_the_status_and_leaves_the_start_alone(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """The one column a replay could corrupt is the one nothing may touch
    twice, so it is asserted alongside the column that must move."""
    run_id = await _one_run(writer, value="a", minute=0)
    await writer.complete(run_id=run_id, at=_EPOCH + timedelta(minutes=5))

    page = await lookup.list_runs(external_ref=None, limit=_PAGE, cursor=None)

    (summary,) = page.items
    assert summary.status is RunStatus.COMPLETED
    assert summary.created_at == _EPOCH
    assert summary.updated_at == _EPOCH + timedelta(minutes=5)


async def check_a_filter_returns_only_the_run_carrying_that_reference(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """The question the whole slice exists to answer: an adapter holding
    an engine's own id and nothing else."""
    await _one_run(writer, value="a", minute=0)
    wanted = await _one_run(writer, value="b", minute=1)

    page = await lookup.list_runs(external_ref=_ref("b"), limit=_PAGE, cursor=None)

    assert [summary.run_id for summary in page.items] == [wanted]


async def check_a_filter_matching_nothing_returns_an_empty_page(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    await _one_run(writer, value="a", minute=0)

    page = await lookup.list_runs(external_ref=_ref("absent"), limit=_PAGE, cursor=None)

    assert page.items == []
    assert page.next_cursor is None


async def check_a_filter_matching_a_different_scheme_returns_nothing(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """Both halves of the pair narrow. A value alone could belong to any
    engine's vocabulary, which is why the filter refuses to take one."""
    await _one_run(writer, value="a", minute=0)

    page = await lookup.list_runs(
        external_ref=Identifier(scheme="other-engine", value="a"),
        limit=_PAGE,
        cursor=None,
    )

    assert page.items == []


async def check_two_runs_sharing_a_reference_both_come_back(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """Nothing refuses a duplicate on the way in, so nothing may hide one
    on the way out. A read model that returned one of these would make a
    run that exists in the log invisible."""
    first = await _one_run(writer, value="same", minute=0)
    second = await _one_run(writer, value="same", minute=1)

    page = await lookup.list_runs(external_ref=_ref("same"), limit=_PAGE, cursor=None)

    assert {summary.run_id for summary in page.items} == {first, second}


async def check_runs_come_back_newest_first(lookup: RunSummaryLookup, writer: RunWriter) -> None:
    oldest = await _one_run(writer, value="a", minute=0)
    middle = await _one_run(writer, value="b", minute=1)
    newest = await _one_run(writer, value="c", minute=2)

    page = await lookup.list_runs(external_ref=None, limit=_PAGE, cursor=None)

    assert [summary.run_id for summary in page.items] == [newest, middle, oldest]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """Every run exactly once across the two pages, in one order. A
    boundary that repeated a row or dropped one would still satisfy a
    check that only counted them."""
    ids = [await _one_run(writer, value=f"v{i}", minute=i) for i in range(5)]

    first = await lookup.list_runs(external_ref=None, limit=2, cursor=None)
    assert first.next_cursor is not None

    second = await lookup.list_runs(external_ref=None, limit=2, cursor=first.next_cursor)
    assert second.next_cursor is not None

    third = await lookup.list_runs(external_ref=None, limit=2, cursor=second.next_cursor)
    assert third.next_cursor is None

    walked = [summary.run_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """A page exactly as long as the limit is still the last page when
    nothing follows it. Handing back a cursor here would send a caller
    round again for nothing."""
    await _one_run(writer, value="a", minute=0)
    await _one_run(writer, value="b", minute=1)

    page = await lookup.list_runs(external_ref=None, limit=2, cursor=None)

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """Paging and filtering compose. A second page that forgot the filter
    would return runs the first page had excluded."""
    await _one_run(writer, value="other", minute=0)
    wanted = [await _one_run(writer, value="same", minute=i) for i in (1, 2, 3)]

    first = await lookup.list_runs(external_ref=_ref("same"), limit=2, cursor=None)
    second = await lookup.list_runs(external_ref=_ref("same"), limit=2, cursor=first.next_cursor)

    walked = [summary.run_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_runs(external_ref=None, limit=_PAGE, cursor="not-a-cursor")


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: RunSummaryLookup, writer: RunWriter
) -> None:
    """A well-formed cursor pointing before everything is not an error. It
    is a caller resuming an execution that has nothing left in it."""
    await _one_run(writer, value="a", minute=10)

    page = await lookup.list_runs(
        external_ref=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_reported_run_shows_as_running_at_the_time_it_was_reported,
    check_an_ending_moves_the_status_and_leaves_the_start_alone,
    check_a_filter_returns_only_the_run_carrying_that_reference,
    check_a_filter_matching_nothing_returns_an_empty_page,
    check_a_filter_matching_a_different_scheme_returns_nothing,
    check_two_runs_sharing_a_reference_both_come_back,
    check_runs_come_back_newest_first,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
)
"""Every check above. Hand-written; the drivers guard against omissions."""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    Deriving the other side from the module's own namespace means adding
    a check and forgetting to list it fails, rather than passing quietly
    with one behaviour fewer than the file appears to promise.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)
