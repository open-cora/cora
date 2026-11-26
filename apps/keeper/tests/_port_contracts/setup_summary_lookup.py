"""Behaviour every `SetupSummaryLookup` adapter owes its callers.

The operation lookup's contract, for the aggregate that changes after it
is defined, and the same reason for existing: one side reads a table a
worker maintains, the other folds every stream, and nothing about the code
on one resembles the other.

Two things are new here and both are where the sides could part. A setup
is revised, so a row moves after it is written, and the two sides have to
agree on which revision it is at, when that revision was made, and that
the move does not change where the row sits in a listing. And a setup has
a key, so the sides have to agree on what one lookup by it returns,
including the case where a race let two setups under one key through.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.setup.state import SetupBeamline, SetupName
from keeper.execution.aggregates.setup.summary import SetupSummaryLookup
from keeper.infrastructure.projection.cursor import InvalidCursorError, encode_cursor


class SetupWriter(Protocol):
    """Put setups where the adapter under test will find them."""

    async def define(
        self,
        *,
        setup_id: UUID,
        beamline: SetupBeamline,
        operation_id: UUID,
        name: SetupName,
        at: datetime,
    ) -> None:
        """Write a setup down, at revision 1."""
        ...

    async def revise(self, *, setup_id: UUID, at: datetime) -> None:
        """Write the next revision of a setup written down earlier."""
        ...


Check = Callable[[SetupSummaryLookup, SetupWriter], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""

_EPOCH = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
"""A fixed instant the checks below count minutes from."""

_PAGE = 50
"""A limit wide enough that paging does not interfere with other checks."""

_OPERATION = UUID("00000000-0000-0000-0000-00000000a001")
_OTHER_OPERATION = UUID("00000000-0000-0000-0000-00000000a002")


async def _one_setup(
    writer: SetupWriter,
    *,
    minute: int,
    beamline: str = "2-bm",
    operation_id: UUID = _OPERATION,
    name: str = "tomo-default",
) -> UUID:
    setup_id = uuid4()
    await writer.define(
        setup_id=setup_id,
        beamline=SetupBeamline(beamline),
        operation_id=operation_id,
        name=SetupName(name),
        at=_EPOCH + timedelta(minutes=minute),
    )
    return setup_id


async def _every(
    lookup: SetupSummaryLookup,
    *,
    beamline: str | None = None,
    operation_id: UUID | None = None,
    name: str | None = None,
) -> list[UUID]:
    page = await lookup.list_setups(
        beamline=SetupBeamline(beamline) if beamline is not None else None,
        operation_id=operation_id,
        name=SetupName(name) if name is not None else None,
        limit=_PAGE,
        cursor=None,
    )
    return [summary.setup_id for summary in page.items]


async def check_an_empty_read_model_returns_an_empty_page(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    _ = writer
    page = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=_PAGE, cursor=None
    )
    assert page.items == []
    assert page.next_cursor is None


async def check_a_defined_setup_shows_at_revision_one_with_its_key(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    setup_id = await _one_setup(writer, minute=0)

    page = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.setup_id == setup_id
    assert summary.beamline == SetupBeamline("2-bm")
    assert summary.operation_id == _OPERATION
    assert summary.name == SetupName("tomo-default")
    assert summary.revision == 1
    assert summary.created_at == _EPOCH


async def check_a_setup_never_revised_was_revised_when_it_was_defined(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """The revision on the row is the definition itself, so its time is
    the definition's. A side that left it empty would make every reader
    ordering by it handle a case the other side never produces."""
    await _one_setup(writer, minute=0)

    page = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.revised_at == summary.created_at == _EPOCH


async def check_a_revision_moves_the_number_and_the_time_and_keeps_the_definition(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    setup_id = await _one_setup(writer, minute=0)
    await writer.revise(setup_id=setup_id, at=_EPOCH + timedelta(minutes=10))
    await writer.revise(setup_id=setup_id, at=_EPOCH + timedelta(minutes=20))

    page = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=_PAGE, cursor=None
    )

    (summary,) = page.items
    assert summary.revision == 3
    assert summary.revised_at == _EPOCH + timedelta(minutes=20)
    assert summary.created_at == _EPOCH


async def check_a_revised_setup_keeps_its_place_in_a_listing(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """Newest by definition, not by revision. A side that sorted on the
    revision time would move a setup to the top of the list every time it
    changed, and a caller paging through would meet it twice."""
    older = await _one_setup(writer, minute=0, name="older")
    newer = await _one_setup(writer, minute=1, name="newer")
    await writer.revise(setup_id=older, at=_EPOCH + timedelta(minutes=30))

    assert await _every(lookup) == [newer, older]


async def check_setups_come_back_newest_first(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    oldest = await _one_setup(writer, minute=0, name="a")
    middle = await _one_setup(writer, minute=1, name="b")
    newest = await _one_setup(writer, minute=2, name="c")

    assert await _every(lookup) == [newest, middle, oldest]


async def check_a_beamline_filter_returns_only_that_beamlines_setups(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    wanted = await _one_setup(writer, minute=0, beamline="2-bm")
    await _one_setup(writer, minute=1, beamline="19-bm")

    assert await _every(lookup, beamline="2-bm") == [wanted]


async def check_an_operation_filter_returns_only_the_setups_that_serve_it(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    wanted = await _one_setup(writer, minute=0, operation_id=_OPERATION)
    await _one_setup(writer, minute=1, operation_id=_OTHER_OPERATION)

    assert await _every(lookup, operation_id=_OPERATION) == [wanted]


async def check_a_name_filter_returns_only_the_setups_called_that(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """One name under several operations and beamlines is the ordinary
    case, so a name alone may return several, and each is a different
    setup."""
    first = await _one_setup(writer, minute=0, name="fast", beamline="2-bm")
    second = await _one_setup(writer, minute=1, name="fast", beamline="19-bm")
    await _one_setup(writer, minute=2, name="slow")

    assert await _every(lookup, name="fast") == [second, first]


async def check_a_name_filter_is_an_exact_match_and_not_a_prefix(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    await _one_setup(writer, minute=0, name="tomo-default-binned")

    assert await _every(lookup, name="tomo-default") == []


async def check_the_three_filters_together_narrow_to_the_one_setup_holding_the_key(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    wanted = await _one_setup(writer, minute=0)
    await _one_setup(writer, minute=1, beamline="19-bm")
    await _one_setup(writer, minute=2, operation_id=_OTHER_OPERATION)
    await _one_setup(writer, minute=3, name="other")

    found = await _every(lookup, beamline="2-bm", operation_id=_OPERATION, name="tomo-default")

    assert found == [wanted]


async def check_a_full_page_hands_back_a_cursor_that_continues_it(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """Every setup exactly once across the pages, in one order."""
    ids = [await _one_setup(writer, minute=i, name=f"s{i}") for i in range(5)]

    first = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=2, cursor=None
    )
    second = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=2, cursor=first.next_cursor
    )
    third = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=2, cursor=second.next_cursor
    )

    assert third.next_cursor is None
    walked = [summary.setup_id for page in (first, second, third) for summary in page.items]
    assert walked == list(reversed(ids))


async def check_the_last_page_hands_back_no_cursor(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    await _one_setup(writer, minute=0, name="a")
    await _one_setup(writer, minute=1, name="b")

    page = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=2, cursor=None
    )

    assert len(page.items) == 2
    assert page.next_cursor is None


async def check_a_cursor_narrows_within_a_filter(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """Paging and filtering compose: the second page of one beamline's
    setups is still that beamline's."""
    await _one_setup(writer, minute=0, beamline="19-bm")
    wanted = [await _one_setup(writer, minute=i, name=f"s{i}") for i in (1, 2, 3)]

    first = await lookup.list_setups(
        beamline=SetupBeamline("2-bm"), operation_id=None, name=None, limit=2, cursor=None
    )
    second = await lookup.list_setups(
        beamline=SetupBeamline("2-bm"),
        operation_id=None,
        name=None,
        limit=2,
        cursor=first.next_cursor,
    )

    walked = [summary.setup_id for page in (first, second) for summary in page.items]
    assert walked == list(reversed(wanted))


async def check_a_cursor_that_did_not_come_from_a_response_is_refused(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    _ = writer
    with pytest.raises(InvalidCursorError):
        await lookup.list_setups(
            beamline=None, operation_id=None, name=None, limit=_PAGE, cursor="not-a-cursor"
        )


async def check_a_cursor_past_the_end_returns_an_empty_page(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    await _one_setup(writer, minute=10)

    page = await lookup.list_setups(
        beamline=None,
        operation_id=None,
        name=None,
        limit=_PAGE,
        cursor=encode_cursor(created_at=_EPOCH, item_id=UUID(int=0)),
    )

    assert page.items == []


async def check_finding_a_key_nobody_holds_returns_nothing(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    _ = writer
    found = await lookup.find_setup(
        beamline=SetupBeamline("2-bm"), operation_id=_OPERATION, name=SetupName("tomo-default")
    )

    assert found is None


async def check_finding_a_held_key_returns_the_setup_at_its_latest_revision(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    setup_id = await _one_setup(writer, minute=0)
    await writer.revise(setup_id=setup_id, at=_EPOCH + timedelta(minutes=5))

    found = await lookup.find_setup(
        beamline=SetupBeamline("2-bm"), operation_id=_OPERATION, name=SetupName("tomo-default")
    )

    assert found is not None
    assert found.setup_id == setup_id
    assert found.revision == 2


async def check_finding_a_key_matches_all_three_parts_and_no_fewer(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """Each part of the key is checked on its own. A side that dropped one
    would answer a definition at 19-BM with 2-BM's setup and refuse it as
    taken."""
    await _one_setup(writer, minute=0)

    for beamline, operation_id, name in (
        ("19-bm", _OPERATION, "tomo-default"),
        ("2-bm", _OTHER_OPERATION, "tomo-default"),
        ("2-bm", _OPERATION, "tomo-default-binned"),
    ):
        found = await lookup.find_setup(
            beamline=SetupBeamline(beamline), operation_id=operation_id, name=SetupName(name)
        )
        assert found is None, f"{beamline}/{operation_id}/{name} matched a setup it does not name"


async def check_finding_a_key_two_setups_raced_into_returns_the_first_defined(
    lookup: SetupSummaryLookup, writer: SetupWriter
) -> None:
    """The defining handler's refusal is a check and not a lock, so two
    setups can land under one key. Both sides return the one defined
    first, which is the one the check would have kept, and the listing
    shows both."""
    first = await _one_setup(writer, minute=0)
    second = await _one_setup(writer, minute=1)

    found = await lookup.find_setup(
        beamline=SetupBeamline("2-bm"), operation_id=_OPERATION, name=SetupName("tomo-default")
    )

    assert found is not None
    assert found.setup_id == first
    assert await _every(lookup, name="tomo-default") == [second, first]


CHECKS: tuple[Check, ...] = (
    check_an_empty_read_model_returns_an_empty_page,
    check_a_defined_setup_shows_at_revision_one_with_its_key,
    check_a_setup_never_revised_was_revised_when_it_was_defined,
    check_a_revision_moves_the_number_and_the_time_and_keeps_the_definition,
    check_a_revised_setup_keeps_its_place_in_a_listing,
    check_setups_come_back_newest_first,
    check_a_beamline_filter_returns_only_that_beamlines_setups,
    check_an_operation_filter_returns_only_the_setups_that_serve_it,
    check_a_name_filter_returns_only_the_setups_called_that,
    check_a_name_filter_is_an_exact_match_and_not_a_prefix,
    check_the_three_filters_together_narrow_to_the_one_setup_holding_the_key,
    check_a_full_page_hands_back_a_cursor_that_continues_it,
    check_the_last_page_hands_back_no_cursor,
    check_a_cursor_narrows_within_a_filter,
    check_a_cursor_that_did_not_come_from_a_response_is_refused,
    check_a_cursor_past_the_end_returns_an_empty_page,
    check_finding_a_key_nobody_holds_returns_nothing,
    check_finding_a_held_key_returns_the_setup_at_its_latest_revision,
    check_finding_a_key_matches_all_three_parts_and_no_fewer,
    check_finding_a_key_two_setups_raced_into_returns_the_first_defined,
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
