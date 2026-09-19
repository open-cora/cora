"""Execution bounded context.

Owns what this system can be asked to run, and what happened when it ran.
Two aggregates are planned for that sentence and one is here:

    plan   a runnable routine, by the name the engine knows it by, and
           the schema its parameters must satisfy.

    run    one carrying-out of a plan. Not written yet.

They will share a context rather than splitting into two, because a run
cannot exist without the plan it ran and checking one against the other
is the whole of what a run's genesis will do. Across a context boundary
that check would have to reach through a sibling's read-side surface for
a relationship neither side can be without.

## Who drove the act

A run this system performed and a run it was merely told about are
different facts, and the aggregate that will hold them is not written
yet. The axis is named here so the word is settled before anything
depends on it: REPORTED for an act an engine performed and told this
system about afterwards, CONDUCTED for one this system drove itself.
"""

from aroc.execution.aggregates.plan import Plan, load_plan
from aroc.execution.errors import UnauthorizedError
from aroc.execution.routes import register_execution_routes
from aroc.execution.tools import register_execution_tools
from aroc.execution.wire import ExecutionHandlers, wire_execution

__all__ = [
    "ExecutionHandlers",
    "Plan",
    "UnauthorizedError",
    "load_plan",
    "register_execution_routes",
    "register_execution_tools",
    "wire_execution",
]
