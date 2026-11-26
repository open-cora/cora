"""The fold-everything setup reader, against the contract both adapters keep.

The operation driver's sibling, same rationale: this is the side that
answers when there is no database, and it reaches its answers by replaying
every setup stream, which is nothing like what the Postgres side does.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.adapters.in_memory_setup_summary_lookup import InMemorySetupSummaryLookup
from keeper.execution.aggregates.operation.state import OperationName
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from tests._port_contracts._writers import EventStoreOperationWriter, EventStoreSetupWriter
from tests._port_contracts.setup_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_setup_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The setup summary contract is empty, so both drivers check nothing."


def test_every_setup_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_setup_summary_lookup_keeps_the_port_contract(check: Check) -> None:
    event_store = InMemoryEventStore()
    await check(InMemorySetupSummaryLookup(event_store), EventStoreSetupWriter(event_store))


async def test_an_operation_stream_in_the_same_store_is_not_read_as_a_setup() -> None:
    """Every aggregate in the process shares one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps an operation out
    of a list of setups, and the Postgres side gets that for free from
    subscribing to setup event types only.

    An operation is the neighbour worth using: a setup serves one, so the
    two always sit in the same store, and both carry a name."""
    event_store = InMemoryEventStore()
    await EventStoreOperationWriter(event_store).define(
        operation_id=uuid4(), name=OperationName("process"), at=datetime.now(tz=UTC)
    )

    page = await InMemorySetupSummaryLookup(event_store).list_setups(
        beamline=None, operation_id=None, name=None, limit=10, cursor=None
    )

    assert page.items == []
