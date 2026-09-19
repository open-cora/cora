"""The decision that reporting a run produces.

The first decider in this tree that takes another aggregate's state as
input. What that buys is visible here: every case below builds a plan
directly and hands it over, with no store, no pool and no await, so the
rule being tested is the rule and not the plumbing around it.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from aroc.execution.aggregates.plan import Plan, PlanName
from aroc.execution.aggregates.run import (
    InvalidRunParametersError,
    Run,
    RunAlreadyExistsError,
    RunReported,
)
from aroc.execution.features.report_run import (
    ReportRun,
    ReportRunContext,
    decide,
)
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 11, 15, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "exposure_seconds": {"type": "number", "minimum": 0},
        "detector": {"type": "string", "enum": ["pilatus", "eiger"]},
    },
    "required": ["exposure_seconds"],
}

_REF = Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")


def _plan(schema: dict[str, Any] | None = None) -> Plan:
    return Plan(
        id=uuid4(),
        name=PlanName("count"),
        parameters_schema=_SCHEMA if schema is None else schema,
    )


def test_recording_a_run_emits_one_event_carrying_the_plan_and_the_reference() -> None:
    plan, new_id = _plan(), uuid4()
    parameters = {"exposure_seconds": 0.25, "detector": "eiger"}

    events = decide(
        None,
        ReportRun(plan_id=plan.id, parameters=parameters, external_ref=_REF),
        context=ReportRunContext(plan=plan),
        now=_NOW,
        new_id=new_id,
    )

    assert events == [
        RunReported(
            run_id=new_id,
            plan_id=plan.id,
            parameters=parameters,
            external_ref_scheme="bluesky-run-uid",
            external_ref_value="f1e2d3c4",
            occurred_at=_NOW,
        )
    ]


def test_recording_a_run_on_a_live_stream_is_refused() -> None:
    plan = _plan()
    existing = Run(
        id=uuid4(),
        plan_id=plan.id,
        parameters={"exposure_seconds": 0.25},
        external_ref=_REF,
    )

    with pytest.raises(RunAlreadyExistsError):
        decide(
            existing,
            ReportRun(plan_id=plan.id, parameters={"exposure_seconds": 0.25}, external_ref=_REF),
            context=ReportRunContext(plan=plan),
            now=_NOW,
            new_id=uuid4(),
        )


def test_parameters_that_break_the_plans_schema_are_refused() -> None:
    """The reason the plan is loaded at all, in one case.

    A negative exposure satisfies the type and fails the bound. Nothing
    about the run itself can catch that; only the plan knows what it
    declared.
    """
    plan = _plan()

    with pytest.raises(InvalidRunParametersError, match="exposure_seconds"):
        decide(
            None,
            ReportRun(plan_id=plan.id, parameters={"exposure_seconds": -1}, external_ref=_REF),
            context=ReportRunContext(plan=plan),
            now=_NOW,
            new_id=uuid4(),
        )


def test_a_parameter_outside_the_plans_enumerated_values_is_refused() -> None:
    plan = _plan()

    with pytest.raises(InvalidRunParametersError):
        decide(
            None,
            ReportRun(
                plan_id=plan.id,
                parameters={"exposure_seconds": 0.25, "detector": "not-a-detector"},
                external_ref=_REF,
            ),
            context=ReportRunContext(plan=plan),
            now=_NOW,
            new_id=uuid4(),
        )


def test_the_same_command_is_decided_differently_by_two_contexts() -> None:
    """The context is the input, which is what makes the decider pure.

    One command, sent twice, against two plans that share an id and
    differ only in what they declare. The strict one refuses it and the
    permissive one does not, so the schema the decision turned on can
    only have come from the argument it was handed. Nothing else in the
    two calls differs, and the decider has nowhere else to look.
    """
    strict = _plan()
    permissive = Plan(
        id=strict.id,
        name=strict.name,
        parameters_schema={"$schema": "https://json-schema.org/draft/2020-12/schema"},
    )
    command = ReportRun(plan_id=strict.id, parameters={"exposure_seconds": -1}, external_ref=_REF)

    with pytest.raises(InvalidRunParametersError):
        decide(
            None,
            command,
            context=ReportRunContext(plan=strict),
            now=_NOW,
            new_id=uuid4(),
        )

    events = decide(
        None,
        command,
        context=ReportRunContext(plan=permissive),
        now=_NOW,
        new_id=uuid4(),
    )
    assert events[0].parameters == {"exposure_seconds": -1}


def test_a_run_with_no_parameters_is_accepted_when_the_schema_requires_none() -> None:
    """Empty values are not checked against `required` at this layer.

    That is the shared validator's documented posture, and it is worth
    one test here so the behaviour is recorded at the aggregate that
    depends on it rather than only at the helper.
    """
    plan = _plan()

    events = decide(
        None,
        ReportRun(plan_id=plan.id, parameters={}, external_ref=_REF),
        context=ReportRunContext(plan=plan),
        now=_NOW,
        new_id=uuid4(),
    )

    assert events[0].parameters == {}
