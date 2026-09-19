"""What the run projection claims, checked without a database.

Three claims, and none of them needs SQL. The projection hears about every
event the aggregate can produce; the status it writes for each one is the
status the evolver would derive; and the name it registers under is the
name the table and the bookmark carry.

What a database IS needed for is whether the SQL does what the strings
say, and that is `tests/integration/test_postgres_run_summary_lookup.py`.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aroc.execution.aggregates.run.events import (
    RunAborted,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunPaused,
    RunResumed,
)
from aroc.execution.aggregates.run.evolver import evolve
from aroc.execution.aggregates.run.state import Run, RunStatus
from aroc.execution.projections.run_summary import (
    PROJECTION_NAME,
    STATUS_BY_EVENT_TYPE,
    RunSummaryProjection,
)
from aroc.infrastructure.projection.registry import ProjectionRegistry
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_RUN_ID = uuid4()
_NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

_TRANSITIONS: tuple[RunEvent, ...] = (
    RunCompleted(run_id=_RUN_ID, occurred_at=_NOW),
    RunAborted(run_id=_RUN_ID, occurred_at=_NOW),
    RunFailed(run_id=_RUN_ID, occurred_at=_NOW),
    RunPaused(run_id=_RUN_ID, occurred_at=_NOW),
    RunResumed(run_id=_RUN_ID, occurred_at=_NOW),
)
"""Every event that moves a run, one instance each.

Spelled out rather than derived from the union, so a seventh event class
added without deciding what the projection does with it fails the coverage
check below rather than quietly joining a generated list.
"""


def _running() -> Run:
    return Run(
        id=_RUN_ID,
        plan_id=uuid4(),
        parameters={},
        external_ref=Identifier(scheme="bluesky-run-uid", value="a"),
        status=RunStatus.RUNNING,
    )


def test_the_projection_hears_about_every_event_a_run_can_produce() -> None:
    """A projection subscribed to four of the six leaves runs frozen in
    whatever status the missing events would have moved them to, and
    nothing else would say so: the table looks right for every run that
    never took the missing transition."""
    every_event_type = {type(event).__name__ for event in _TRANSITIONS} | {"RunReported"}

    assert RunSummaryProjection.subscribed_event_types == frozenset(every_event_type)


@pytest.mark.parametrize("event", _TRANSITIONS, ids=lambda e: type(e).__name__)
def test_the_projection_and_the_evolver_agree_on_every_status(event: RunEvent) -> None:
    """The projection maps an event type to a status with a table, and the
    evolver derives the same value by folding. Two answers to one question,
    written in two places, so this is the check that keeps them one answer.
    """
    folded = evolve(_running(), event)

    assert folded is not None
    assert STATUS_BY_EVENT_TYPE[type(event).__name__] is folded.status


def test_a_genesis_is_the_one_event_the_status_table_leaves_out() -> None:
    """`RunReported` writes `Running` as part of inserting the row, so it
    is deliberately absent from the transition table. Listing it there
    would make an insert reachable through the update path, which would
    silently do nothing."""
    assert "RunReported" not in STATUS_BY_EVENT_TYPE
    assert "RunReported" in RunSummaryProjection.subscribed_event_types


def test_the_projection_registers_under_the_name_its_table_carries() -> None:
    """The name keys the bookmark row, the table and the registration, and
    nothing in the type system ties the three together."""
    registry = ProjectionRegistry()
    registry.register(RunSummaryProjection())

    assert registry.names() == frozenset({PROJECTION_NAME})
    assert PROJECTION_NAME == "proj_execution_run_summary"
