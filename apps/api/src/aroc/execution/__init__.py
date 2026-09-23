"""Execution bounded context.

Owns what this system can be asked to run, and what happened when it ran.

    plan   a runnable routine, by the name the execution layer knows it
           by, and the schema its parameters must satisfy.

    run    one execution of a plan: which plan, with what parameters,
           and what the engine that ran it calls the result.

    walk   one traversal of a procedure: the steps it was asked to
           perform, and how each of them ended.

Plan and run share a context because a run cannot exist without the plan
it ran and checking one against the other is the whole of what a run's
genesis does. Across a context boundary that check would have to reach
through a sibling's read-side surface for a relationship neither side
can be without.

A walk is here because it is the same shape one scale up. A procedure is
to a walk what a plan is to a run: the routine, and one carrying-out of
it. Most of a walk's steps cause no run at all, which is why a walk
cannot be recorded as one, and the steps that do cause one nest under it
rather than beside it.

Nothing holds procedures yet, so a walk carries its own step list rather
than citing one. That stays true after a procedure aggregate lands: a
walk citing a definition would become a record of the wrong thing the
moment that definition was edited.

## Who drove the act

The near-term direction is REPORTED: an engine runs the routine, and
afterwards someone or something tells this system that it did.
CONDUCTED, where this system drives the act across an adapter, comes
after.

Reported rather than witnessed, which was the first word here and was
wrong. To witness is to have been present and able to vouch for what
happened. This system is neither. It is told, by an HTTP caller today
and by an adapter draining an engine's output later, and in both cases
the whole of what it knows is that it was told. A word claiming more
than that would be the kind of unbacked claim this tree refuses
everywhere else.

There is no field naming the axis, and there is not going to be one.
Reporting a run and conducting one are different commands, and the
naming rule makes each derive its own genesis event, so which event
opened a stream is what says who drove the act. A distinction carried
by the class rather than by a flag cannot be set wrong.

The verb follows from the same place. This context's genesis command is
`report_run`, because this system did not start anything; a command
claiming otherwise waits for the path that earns it.
"""

from aroc.execution.aggregates.plan import Plan, load_plan
from aroc.execution.aggregates.run import Run, load_run
from aroc.execution.aggregates.walk import Walk, load_walk
from aroc.execution.errors import UnauthorizedError
from aroc.execution.projections import register_execution_projections
from aroc.execution.routes import register_execution_routes
from aroc.execution.tools import register_execution_tools
from aroc.execution.wire import ExecutionHandlers, wire_execution

__all__ = [
    "ExecutionHandlers",
    "Plan",
    "Run",
    "UnauthorizedError",
    "Walk",
    "load_plan",
    "load_run",
    "load_walk",
    "register_execution_projections",
    "register_execution_routes",
    "register_execution_tools",
    "wire_execution",
]
