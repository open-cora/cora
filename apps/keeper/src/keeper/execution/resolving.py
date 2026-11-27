"""Find the setups a procedure's runs name, as the procedure's beamline holds them now.

A run of an operation that takes a setup names one by its `config`, and
the decisions that check such a run are pure: they cannot ask a store
which setup a name means. So whoever is about to decide reads the setups
first and hands them across, and every such reader asks the same way,
which is here.

Four callers. Defining a procedure and dispatching one, in this context,
and adopting a proposal, from Counsel and from Pursuit, where its runs are
composed through `compose_runs`. The adopting two cannot be handed a
read port by this context's wiring, which builds nothing for them, so the
one function they call takes the kernel and picks the port itself.

## Read by name, and why that is not a lock either

A setup is found by its key, through the summary a projection keeps, and
then folded from its own stream to its latest revision. The key comes
from the table, which may lag the log by the time a definition takes to
reach it: a setup defined a moment ago may not be found yet, and the
caller refuses as though it did not exist. Asking again a moment later
finds it. The revision comes from the stream, which does not lag, so
what a caller is handed is the latest revision this system holds rather
than the latest the table has caught up with.

Nothing here holds the answer still. A revision landing between this read
and the caller's append is not seen, which is the window a definition and
a dispatch accept for every sibling they read.

## Lazily

Nothing is read, and no read port is even chosen, unless some run names a
setup. A procedure of sets, or of runs whose operations take none, costs
exactly what it cost before setups existed.
"""

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from keeper.execution.adapters import InMemorySetupSummaryLookup, PostgresSetupSummaryLookup
from keeper.execution.aggregates.operation import Operation
from keeper.execution.aggregates.setup import (
    InvalidSetupBeamlineError,
    Setup,
    SetupBeamline,
    SetupName,
    SetupSummaryLookup,
    can_take_a_setup,
    load_setup,
    named_setup,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel, UnreadableSummariesError


def setup_summary_lookup(deps: Kernel) -> SetupSummaryLookup:
    """Pick the read adapter for setups: the table where there is a pool, a fold where there is not.

    The one place the choice is made. The wiring module calls this for the
    listing and the definition slices it builds, and `resolve_setups` calls
    it for the callers the wiring does not build.
    """
    if deps.pool is not None:
        return PostgresSetupSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemorySetupSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


async def resolve_setups(
    deps: Kernel,
    *,
    beamline: str,
    runs: Iterable[tuple[Operation, Mapping[str, Any]]],
) -> dict[tuple[UUID, SetupName], Setup]:
    """Each setup the runs name at this beamline, at its latest revision, by operation and name.

    A run is each operation paired with the parameters it runs with. Only
    runs whose operation can take a setup and whose `config` is a name a
    setup could hold are looked up, each distinct key once. A key no setup
    holds is simply absent from the answer: refusing it is the decider's,
    which says which step and why.

    A beamline no setup could be held at, empty or over the bound, finds
    nothing, for the same reason: the caller's own refusal of that
    beamline is the one to hear, not one about setups.
    """
    keys: set[tuple[UUID, SetupName]] = set()
    for operation, parameters in runs:
        if not can_take_a_setup(operation.parameters_schema):
            continue
        name = named_setup(parameters)
        if name is not None:
            keys.add((operation.id, name))
    if not keys:
        return {}
    try:
        place = SetupBeamline(beamline)
    except InvalidSetupBeamlineError:
        return {}

    lookup = setup_summary_lookup(deps)
    found: dict[tuple[UUID, SetupName], Setup] = {}
    for operation_id, name in sorted(keys, key=lambda key: (str(key[0]), key[1].value)):
        summary = await lookup.find_setup(beamline=place, operation_id=operation_id, name=name)
        if summary is None:
            continue
        setup = await load_setup(deps.event_store, summary.setup_id)
        if setup is not None:
            found[(operation_id, name)] = setup
    return found


__all__ = ["resolve_setups", "setup_summary_lookup"]
