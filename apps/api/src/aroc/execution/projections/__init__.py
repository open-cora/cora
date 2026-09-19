"""Execution's read-side projections, and the call that subscribes them.

The composition root calls `register_execution_projections` once during
startup, after `wire_execution` and before the worker starts. Mechanical
by design: the registry decides nothing, it holds what it is given, so
everything interesting about a projection is in the projection.

## Why the registrar is here rather than at the context root

The context's other three plug points are one flat module each, named
for the call the composition root makes: `wire.py`, `routes.py`,
`tools.py`. The fourth cannot join them under the matching name, because
a module and a package cannot share one name inside a package, and the
package is where the projections themselves belong.

That left a made-up filename nobody would choose on its own, or the
registrar living with the things it registers. The second reads better:
the code that says which projections exist sits beside them, and the
count is checked by looking in one place.

An `__init__.py` holding a function is otherwise unheard of in this
tree, where all of them are a docstring and re-exports. It is deliberate
here and nowhere else. This package has exactly one subject, so a
registrar over its own contents is not logic smuggled into a namespace;
a function in a context root's `__init__.py` would be.

## `PROJECTION_NAME` is deliberately not re-exported

Each projection module defines one and they are different strings, so a
package-level name would have to pick a winner and every importer would
be one rename away from querying the wrong table. Import it from the
module whose table you mean.
"""

from aroc.execution.projections.plan_summary import PlanSummaryProjection
from aroc.execution.projections.run_summary import (
    STATUS_BY_EVENT_TYPE,
    RunSummaryProjection,
)
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.projection.registry import ProjectionRegistry


def register_execution_projections(registry: ProjectionRegistry, deps: Kernel) -> None:
    """Register every Execution projection with the worker's registry.

    `deps` is unused today and is in the signature anyway, because the
    signature is the one every context implements and a projection that
    needs the clock or the id generator should not have to change the
    shape of this call to get them.

    `test_every_bc_is_mounted.py` checks that the composition root
    actually makes the call, which is the failure this would otherwise
    have: a projection that is written, tested, and never subscribed,
    leaving a read model empty while every write succeeds.
    """
    _ = deps
    registry.register(RunSummaryProjection())
    registry.register(PlanSummaryProjection())


__all__ = [
    "STATUS_BY_EVENT_TYPE",
    "PlanSummaryProjection",
    "RunSummaryProjection",
    "register_execution_projections",
]
