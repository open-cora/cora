"""The state this slice's decision needs from outside its own stream, loaded first.

A decider is pure: it takes values and returns events, and it never reads
from a port. Defining a setup asks two things no setup stream can answer:
whether the operation it serves can take one, and whether another setup
already holds its key. The handler reads both and hands them across as
plain data, the way `define_procedure/context.py` hands across the
operations a procedure's runs cite.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.operation import Operation


@dataclass(frozen=True)
class DefineSetupContext:
    """The operation the setup serves, and the setup already holding its key.

    `operation` is always present. The handler refuses a setup for an
    operation that does not exist before building this, so the decider may
    read its status and its schema without handling a miss.

    `existing_setup_id` is the setup that already holds the same name for
    the same operation at the same beamline, or None when the key is free.
    An id rather than the whole summary, because the id is all the refusal
    carries: it names the setup the caller should revise instead.

    Both were read at handler time, so both can be stale by the time the
    append lands. That is accepted for the operation, as a procedure accepts
    it for the operations it cites. For the key it is the window the
    handler's docstring describes, and it is why this is a check and not a
    lock.
    """

    operation: Operation
    existing_setup_id: UUID | None


__all__ = ["DefineSetupContext"]
