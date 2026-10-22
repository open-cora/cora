"""Every step event in the aggregate's union reaches the projections.

A projection subscribes by event-type string, so a new member of the
aggregate's event union is not wired to anything until somebody adds its
name to a frozenset in another file. Nothing failed when that was
skipped: the type checker sees no relationship between a class and a
string, and the suite exercises the projections through the events it
already knew about.

What that costs is quiet and total. An unsubscribed outcome never
reaches `ExecutionSummaryProjection`, so the execution's row never
counts that step as reported and a finished execution reads as one still
waiting on it. The same event never reaches `StepSummaryProjection`, so
the step keeps no outcome at all.

Both of those sets already said in prose that a check reads them. None
did. This is that check, and the sets are public so that it can.

The partition is by name, because the two kinds of step event differ by
who reports them rather than by anything in their shape: an engine event
is what something watching an engine said, and everything else is what
the driver said.
"""

from __future__ import annotations

import typing

import pytest

from keeper.execution.aggregates.execution import ExecutionEvent
from keeper.execution.projections.execution_summary import ENGINE_EVENT_TYPES, STEP_EVENT_TYPES
from keeper.execution.projections.step_summary import OUTCOME_EVENT_TYPES, outcome_word_for

pytestmark = pytest.mark.architecture

_STEP_PREFIX = "ExecutionStep"
_ENGINE_PREFIX = "ExecutionStepEngine"


def _union_names() -> frozenset[str]:
    return frozenset(member.__name__ for member in typing.get_args(ExecutionEvent))


def _driver_reported() -> frozenset[str]:
    """Step events the driver sends: every step event that is not an engine one."""
    return frozenset(
        name
        for name in _union_names()
        if name.startswith(_STEP_PREFIX) and not name.startswith(_ENGINE_PREFIX)
    )


def _engine_reported() -> frozenset[str]:
    return frozenset(name for name in _union_names() if name.startswith(_ENGINE_PREFIX))


def test_the_execution_summary_subscribes_every_outcome_the_union_holds() -> None:
    assert _driver_reported() == STEP_EVENT_TYPES


def test_the_execution_summary_subscribes_every_engine_event_the_union_holds() -> None:
    assert _engine_reported() == ENGINE_EVENT_TYPES


def test_the_step_summary_subscribes_every_outcome_the_union_holds() -> None:
    assert _driver_reported() == OUTCOME_EVENT_TYPES


@pytest.mark.parametrize("event_type", sorted(_driver_reported()))
def test_the_step_summary_has_a_word_for_every_outcome_it_subscribes(event_type: str) -> None:
    """A subscribed event with no word would write a null outcome and look reported."""
    assert outcome_word_for(event_type)
