"""Walks a procedure across a beamline's seams, one claim at a time.

A client of the keeper rather than a part of it, the same way `apps/reporter`
is. It composes a routine nothing outside knows, drives it through three
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
from conductor.conduct import Walk, conduct
from conductor.intake import serve
from conductor.outcomes import Broke, Declined, Done, Outcome, Refused, Skipped
from conductor.procedure import (
    InvalidProcedureError,
    Procedure,
    Step,
)
from conductor.repertoire import Repertoire, RoutineClaimedTwiceError
from conductor.seams import (
    Assignment,
    Citation,
    Ran,
    ReferenceNotCarriedError,
    Reporting,
    RoutineNotRunHereError,
    Running,
    Tasking,
)

__all__ = [
    "Assignment",
    "Broke",
    "Citation",
    "Claim",
    "ClaimConflictError",
    "Declined",
    "Done",
    "InvalidProcedureError",
    "InvalidScopeError",
    "Ledger",
    "Outcome",
    "Procedure",
    "Ran",
    "ReferenceNotCarriedError",
    "Refused",
    "Repertoire",
    "Reporting",
    "RoutineClaimedTwiceError",
    "RoutineNotRunHereError",
    "Running",
    "Scope",
    "Skipped",
    "Step",
    "Tasking",
    "Walk",
    "conduct",
    "serve",
]
