"""The fold-everything read adapter, against the contract both adapters keep.

This is the side that answers when there is no database, which is the
environment the unit and contract tiers run in and the one the Bluesky
spike drives. It reaches its answers by replaying every run stream, which
is nothing like what the Postgres side does, so the two agreeing is worth
asserting rather than assuming.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aroc.execution.adapters.in_memory_run_summary_lookup import InMemoryRunSummaryLookup
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.identifier import Identifier
from tests._port_contracts._run_writer import EventStoreRunWriter
from tests._port_contracts.run_summary_lookup import (
    CHECKS,
    Check,
    checks_defined_but_not_listed,
)

pytestmark = pytest.mark.unit


def test_the_run_summary_contract_lists_at_least_one_check() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert CHECKS, "The run summary contract is empty, so both drivers check nothing."


def test_every_run_summary_check_written_is_a_check_that_runs() -> None:
    unlisted = checks_defined_but_not_listed()
    assert not unlisted, (
        f"Defined but missing from CHECKS: {sorted(unlisted)}.\n"
        "A check absent from the tuple runs against neither adapter."
    )


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_in_memory_run_summary_lookup_keeps_the_port_contract(check: Check) -> None:
    event_store = InMemoryEventStore()
    await check(InMemoryRunSummaryLookup(event_store), EventStoreRunWriter(event_store))


async def test_a_plan_stream_in_the_same_store_is_not_read_as_a_run() -> None:
    """Every aggregate in the process shares one store, and this adapter
    enumerates it. Enumerating by stream type is what keeps a plan out of
    a list of runs, and the Postgres side gets that for free from
    subscribing to run event types only."""
    event_store = InMemoryEventStore()
    await event_store.append(
        "Plan",
        uuid4(),
        0,
        [
            to_new_event(
                event_type="PlanDefined",
                payload={"name": "count"},
                occurred_at=datetime.now(tz=UTC),
                event_id=uuid4(),
                command_name="DefinePlan",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    await EventStoreRunWriter(event_store).report(
        run_id=uuid4(),
        plan_id=uuid4(),
        external_ref=Identifier(scheme="bluesky-run-uid", value="a"),
        at=datetime.now(tz=UTC),
    )

    page = await InMemoryRunSummaryLookup(event_store).list_runs(
        external_ref=None, limit=10, cursor=None
    )

    assert len(page.items) == 1
