"""Hand Execution's projections to the worker that advances them.

The composition root calls this once during startup, after `wire_execution`
and before the worker starts. Mechanical by design: the registry decides
nothing, it holds what it is given, so everything interesting about a
projection is in the projection.

`deps` is unused today and is in the signature anyway, because the
signature is the one every context implements and a projection that needs
the clock or the id generator should not have to change the shape of this
call to get them. `test_every_bc_is_mounted.py` checks that the
composition root actually makes the call, which is the failure this file
would otherwise have: a projection that is written, tested, and never
subscribed, leaving a read model empty while every write succeeds.
"""

from aroc.execution.projections import RunSummaryProjection
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.projection.registry import ProjectionRegistry


def register_execution_projections(registry: ProjectionRegistry, deps: Kernel) -> None:
    """Register every Execution projection with the worker's registry."""
    _ = deps
    registry.register(RunSummaryProjection())


__all__ = ["register_execution_projections"]
