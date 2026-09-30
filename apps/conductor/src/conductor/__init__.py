"""Walks a procedure across a beamline's seams, one claim at a time.

A client of the keeper rather than a part of it, the same way `apps/reporter`
is. It composes a routine nothing outside knows, drives it through five
seams named for what it does through them, and the runs it causes reach
the keeper through the surface that already exists. Nothing here imports
`keeper` and nothing in `apps/keeper` imports this.

What it is for, in one sentence: to be the thing that knows which step
holds which device, because when nothing does, two writers reach one
motor and both report success.

`serve` is the loop `python -m conductor` runs, exported because a
deployment that already has a long-running process would rather call it
than start a second one. It is given its seams, so importing this still costs no
outside library.
"""

from conductor.claims import (
    Claim,
    ClaimConflictError,
    InvalidScopeError,
    Ledger,
    Scope,
)
from conductor.conduct import Unfiled, Walk, conduct
from conductor.intake import serve
from conductor.outcomes import Broke, Done, Outcome, Refused, Skipped
from conductor.procedure import (
    InvalidProcedureError,
    Procedure,
    Run,
    Set,
    Step,
)
from conductor.seams import (
    Address,
    Adjusting,
    Assignment,
    Citation,
    Filing,
    Ran,
    ReferenceNotCarriedError,
    Reporting,
    Running,
    Tasking,
)

__all__ = [
    "Address",
    "Adjusting",
    "Assignment",
    "Broke",
    "Citation",
    "Claim",
    "ClaimConflictError",
    "Done",
    "Filing",
    "InvalidProcedureError",
    "InvalidScopeError",
    "Ledger",
    "Outcome",
    "Procedure",
    "Ran",
    "ReferenceNotCarriedError",
    "Refused",
    "Reporting",
    "Run",
    "Running",
    "Scope",
    "Set",
    "Skipped",
    "Step",
    "Tasking",
    "Unfiled",
    "Walk",
    "conduct",
    "serve",
]
