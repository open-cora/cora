"""Walks a procedure across a beamline's seams, one claim at a time.

A client of AROC rather than a part of it, the same way `apps/reporter`
is. It composes a routine nothing outside knows, drives it through three
seams, and the runs it causes reach AROC through the surface that already
exists. Nothing here imports `aroc` and nothing in `apps/api` imports
this.

What it is for, in one sentence: to be the thing that knows which step
holds which device, because `spikes/conductor/FINDINGS.md` measured what
happens when nothing does.

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
from conductor.outcomes import Broke, Done, Outcome, Refused, Skipped
from conductor.procedure import (
    Acquire,
    InvalidProcedureError,
    Move,
    Procedure,
    Step,
)
from conductor.seams import (
    Acquired,
    Acquisition,
    Aroc,
    Assignment,
    Citation,
    Control,
    Reporting,
)

__all__ = [
    "Acquire",
    "Acquired",
    "Acquisition",
    "Aroc",
    "Assignment",
    "Broke",
    "Citation",
    "Claim",
    "ClaimConflictError",
    "Control",
    "Done",
    "InvalidProcedureError",
    "InvalidScopeError",
    "Ledger",
    "Move",
    "Outcome",
    "Procedure",
    "Refused",
    "Reporting",
    "Scope",
    "Skipped",
    "Step",
    "Walk",
    "conduct",
    "serve",
]
