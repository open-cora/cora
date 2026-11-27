"""Compose the writes that dispatch a sequence of runs.

A procedure with one run step per run, in order, and the execution that
traverses it, decided together and handed back as appends for somebody
else to commit. Nothing here touches the store.

## Why this exists at all

Advice becomes work by composing a procedure around what was advised and
dispatching an execution against it, in one transaction with whatever the
caller is recording on its own stream. That transaction cannot live here,
because the thing being recorded belongs to the caller's context and this
one knows nothing of it. So the decisions stay here, where the aggregates
they are about are modelled, and only the append moves.

The first caller assembled this itself, from six of this context's names
plus two stream types and two payload renderers, and the door said so.
What it knew was not just what it wanted but how this context gets there:
that a procedure is defined and then dispatched, that dispatching needs
the procedure as a value rather than an id, that the value has to be
folded out of an event that is not stored yet, and which of the two
streams each rendering goes on. None of that is the caller's business,
and all of it would have broken the caller when it changed.

A second caller arriving is what made that worth fixing rather than
noting. Two contexts each holding the same account of how this one
composes is two places to change and one to forget.

It composed one run until a proposal could put forward several. Several
runs are one procedure and one execution rather than one of each per run,
because they were advised together and are meant to run in that order,
and a driver that walked them as separate executions could interleave
somebody else's work between a collection and the transfer of its data.

## What the caller still supplies, and why

The setups the runs name, already resolved. A run of an operation that
takes a setup names one by its `config`, and both decisions here check
it against the setup that name means at the beamline. Finding that setup
reads a store, which nothing here does, so the caller asks
`keeper.execution.resolving.resolve_setups` first and passes the answer
through untouched.

Two callables rather than values.

`new_id` because the ids are minted here and a decision has to be
reproducible on replay, so they arrive from the caller's port rather than
from anything this module reaches for.

`envelope` because a stored event carries an event id, a command name, a
correlation id and a principal, and every one of those is the caller's. It
is the caller's command that produced these events, so its name is the
honest one to record, and a module that stamped its own would leave the
log saying the procedure was composed by a command nobody issued.

That is also why this hands back `StreamAppend` rather than events: the
enveloping has to happen for the appends to exist, and doing it here with
the caller's own maker keeps the boundary at the right place. What this
module knows is which stream each event belongs on. What the caller knows
is who is asking.

## What each run is allowed to touch

The caller states one bound, `scopes` or `drives_no_device`, and an
operation's declared device use decides how each run takes it. That rule
is here rather than in either caller because both callers need it and it
is about Execution's record.

    declared false    no scopes, and the run says it drives none, whatever
                      the bound was: the facility said so
    declared true     the bound's scopes; a bound saying the run drives
                      nothing is refused, because the facility said it does
    undeclared        the bound exactly, when the run is the only one, which
                      is how every run was composed before anybody could
                      declare; refused when it is one of several, naming
                      the operation, because a composition of several runs
                      has to know what each of them touches

## What it does not decide

Whether the runs should happen. This composes what was asked for and
refuses only what this context's own deciders refuse, plus the device use
above: an operation that has been retired, parameters its schema does not
accept, a setup a run names that the beamline does not hold or whose
schema its override does not fit, scopes that are malformed. Whether there
is budget for it, whether a proposal was already adopted, whether anybody
authorized a beamline: all of that is the caller's, decided before this
is called.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.execution import to_payload as execution_payload
from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationCannotBeComposedError,
)
from keeper.execution.aggregates.procedure import (
    PROCEDURE_NAME_MAX_LENGTH,
    PROCEDURE_STREAM_TYPE,
    InvalidProcedureStepsError,
    RunStep,
)
from keeper.execution.aggregates.procedure import fold as fold_procedure
from keeper.execution.aggregates.procedure import to_payload as procedure_payload
from keeper.execution.aggregates.setup import Setup, SetupName
from keeper.execution.features.define_procedure import DefineProcedure, DefineProcedureContext
from keeper.execution.features.define_procedure import decide as decide_procedure
from keeper.execution.features.dispatch_execution import (
    DispatchExecution,
    DispatchExecutionContext,
)
from keeper.execution.features.dispatch_execution import decide as decide_execution
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend


@dataclass(frozen=True, slots=True)
class ComposedRuns:
    """The writes that would dispatch the runs, and the ids they will create.

    `appends` is in the order the streams were decided, procedure before
    execution, which is also the order a reader of the log would want them.
    The caller adds its own and commits all of them together.

    `execution_id` is what the caller hands back to whoever asked.
    `step_ids` are the runs inside it, one per run and in the order the
    runs were given, which is the thing a record citing a run points at:
    a dataset is produced by one run rather than by a whole traversal,
    and so is a proposal being taken up.
    """

    execution_id: UUID
    step_ids: tuple[UUID, ...]
    appends: tuple[StreamAppend, ...]


def compose_runs(
    *,
    runs: Sequence[tuple[Operation, Mapping[str, Any]]],
    beamline: str,
    scopes: tuple[str, ...],
    drives_no_device: bool,
    setups: Mapping[tuple[UUID, SetupName], Setup],
    now: datetime,
    new_id: Callable[[], UUID],
    envelope: Callable[[str, dict[str, Any], datetime], NewEvent],
) -> ComposedRuns:
    """Decide a procedure around these runs and an execution that traverses it.

    A run is an operation paired with the parameters it runs with, the
    pairing `resolve_setups` takes too. The procedure holds one run step
    per run, in the order given, at the beamline the caller states.

    `beamline`, `scopes` and `drives_no_device` are the caller's because
    nothing here can infer them, and the last two have no defaults for the
    reason the step type gives: an omission and a declaration have to stay
    distinguishable. A default meaning `False` is how a caller says nothing
    while appearing to have spoken. How each run takes them is decided by
    its operation's device use, which the module docstring sets out, and
    every refusal that rule makes is raised before anything is minted.

    A bound naming devices and also saying the runs drive none is refused
    first, whatever the runs' operations declare. The definition refuses
    that contradiction on any one step, and a plan whose every run drives
    nothing would otherwise carry it through unread, because no step built
    from such a run takes the bound at all.

    A retired operation is refused here before any device use is asked
    about, although the definition below refuses it too. Its device use
    can no longer be declared, so a refusal about that would send the
    caller after a fix that cannot be made.

    `setups` has no default either. A run of an operation that takes a
    setup is checked against it twice, once as the procedure is defined
    and once as it is dispatched, and the definition's check is the one
    that refuses, as the run's parameters: the dispatch then asks the same
    question of the same setup and pins the revision it found. An empty
    mapping refuses every such run, so a caller that forgot to resolve
    fails closed rather than dispatching values nobody chose.

    The procedure is folded before it is dispatched because the dispatch
    decider takes a procedure as context and the one being dispatched was
    decided a few lines earlier and is in no store yet. The evolver is pure
    and total, so the value this builds is byte for byte the state a later
    reader will fold out of the same event.

    The ids are minted in a fixed order, the procedure's, one per composed
    step, the execution's, then one per dispatched step, so that a caller
    passing a deterministic generator gets the same composition twice, and
    one run mints exactly the four it always did. Nothing here reads a
    clock: `now` is the caller's, and both deciders stamp it.
    """
    if scopes and drives_no_device:
        msg = (
            "The bound names devices and also says the runs drive none. One of the two "
            "is wrong and this system will not pick which, whatever the runs' operations "
            "declare"
        )
        raise InvalidProcedureStepsError(msg)
    for operation, _parameters in runs:
        if operation.is_retired:
            raise OperationCannotBeCitedError(operation.id, operation.status)
    steps = tuple(
        _run_step(
            index,
            operation,
            parameters,
            scopes=scopes,
            drives_no_device=drives_no_device,
            alone=len(runs) == 1,
        )
        for index, (operation, parameters) in enumerate(runs)
    )
    operations = {operation.id: operation for operation, _parameters in runs}

    procedure_id = new_id()
    composed_step_ids = [new_id() for _ in steps]
    execution_id = new_id()
    dispatched_step_ids = [new_id() for _ in steps]

    procedure_events = decide_procedure(
        None,
        DefineProcedure(
            name=_named_for([operation for operation, _parameters in runs]),
            beamline=beamline,
            steps=steps,
        ),
        context=DefineProcedureContext(operations=operations, setups=setups),
        now=now,
        new_id=procedure_id,
        step_ids=composed_step_ids,
    )
    composed = fold_procedure(procedure_events)
    if composed is None:
        msg = "defining a procedure produced no events, which its decider cannot do"
        raise RuntimeError(msg)

    execution_events = decide_execution(
        None,
        DispatchExecution(procedure_id=procedure_id),
        context=DispatchExecutionContext(procedure=composed, operations=operations, setups=setups),
        now=now,
        new_id=execution_id,
        step_ids=dispatched_step_ids,
    )

    return ComposedRuns(
        execution_id=execution_id,
        step_ids=tuple(dispatched_step_ids),
        appends=(
            StreamAppend(
                stream_type=PROCEDURE_STREAM_TYPE,
                stream_id=procedure_id,
                expected_version=0,
                events=[
                    envelope(type(event).__name__, procedure_payload(event), event.occurred_at)
                    for event in procedure_events
                ],
            ),
            StreamAppend(
                stream_type=EXECUTION_STREAM_TYPE,
                stream_id=execution_id,
                expected_version=0,
                events=[
                    envelope(type(event).__name__, execution_payload(event), event.occurred_at)
                    for event in execution_events
                ],
            ),
        ),
    )


def _run_step(
    index: int,
    operation: Operation,
    parameters: Mapping[str, Any],
    *,
    scopes: tuple[str, ...],
    drives_no_device: bool,
    alone: bool,
) -> RunStep:
    """The run step one run becomes, by its operation's declared device use."""
    if operation.drives_devices is False:
        return RunStep(
            operation_id=operation.id,
            parameters=dict(parameters),
            scopes=(),
            drives_no_device=True,
        )
    if operation.drives_devices is None and not alone:
        raise OperationCannotBeComposedError(operation.id, index, drives_devices=None)
    if operation.drives_devices is True and drives_no_device:
        raise OperationCannotBeComposedError(operation.id, index, drives_devices=True)
    return RunStep(
        operation_id=operation.id,
        parameters=dict(parameters),
        scopes=tuple(scopes),
        drives_no_device=drives_no_device,
    )


def _named_for(operations: Sequence[Operation]) -> str:
    """What the composed procedure is called: the operations it runs, in order.

    One run is named after its operation, as it always was, and a caller
    naming it would be naming something it did not compose. Several are
    named after theirs, joined in the order they run, which is what a
    person scanning a listing of procedures would want to read. A name
    that would not fit the bound is cut short and says so with an
    ellipsis rather than refusing the composition, because a label is the
    wrong thing to refuse work over.
    """
    name = ", ".join(operation.name.value for operation in operations)
    if len(name) <= PROCEDURE_NAME_MAX_LENGTH:
        return name
    return name[: PROCEDURE_NAME_MAX_LENGTH - 3].rstrip(", ") + "..."


__all__ = ["ComposedRuns", "compose_runs"]
