"""The intent: take this advice, and commit the facility to it."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AdoptProposal:
    """Adopt this proposal, at this beamline, over these devices.

    Adopt rather than enact, and rather than accept. Enacting names what
    happens elsewhere, which is a procedure composed and an execution
    dispatched, and this context is named for what it keeps rather than
    for what happens elsewhere. Accepting is reserved for a person
    approving something that may then never run, and spending it here
    would leave that command nothing to be called.

    **Three fields, and two of them are the caller's because nothing here
    can derive them.** A proposal cites operations and carries values, which
    is not enough to compose a procedure out of: `define_procedure` says
    a beamline cannot be derived because the steps imply it in a prefix
    this system deliberately does not parse, and a run
    declaring no devices is refused outright, because a step believed to
    touch nothing can run beside another over the same motor.

    So the bound is stated rather than inferred. A thinker or an
    operator reading the execution a proposal came from can see what
    that operation touched last time and offer those values, and offering is
    where that belongs: a bound the system guessed is one nobody
    decided.

    For a plan the bound is one statement for every run, and what each run
    takes from it is its operation's declared device use rather than
    anything the caller adds. A run of an operation declared to drive
    nothing composes with no scopes whatever the bound says, because the
    facility said so; one declared to drive devices takes the scopes, and
    refuses `drives_no_device`, because the facility said otherwise. That
    is what lets one bound serve a collection and the transfer after it.

    **There is no `occurred_at`.** Adopting is an act this system
    performs and the call is the performing, so there is no earlier
    moment for the record to be late to. That is R8 on the makes side,
    beside `make_proposal` rather than beside `take_proposal`.

    **There is no procedure name.** The routine composed for a proposal is
    named after the operations it runs, in order, which for a proposal of
    one run is that run's operation, and a caller naming it would be naming
    something it did not compose.
    """

    proposal_id: UUID
    beamline: str
    scopes: tuple[str, ...]
    drives_no_device: bool


__all__ = ["AdoptProposal"]
