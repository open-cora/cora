"""Ask the keeper for work at one beamline, take it up, walk it, and ask again.

The loop that turns this package from a library into a process. Nothing
dispatches to a conductor: the keeper writes an execution and holds it, and a
conductor is what goes looking. Four verbs in a fixed order, forever.

    take     hold one request open until something is dispatched here
    claim    say this conductor is driving it, or find out it lost
    conduct  walk it, reporting each step as the step ends, and carrying
             the keeper's ids into the record of every run it opens
    repeat

## Why this is not in `conduct`

A walk is of one procedure and ends. This does not end, and between two
walks it is doing the one thing a walk must never do, which is asking for
more work. Keeping them apart is also what lets `conduct` be handed
`Reporting` rather than the whole seam: the loop holds the four verbs and
gives a walk the two it needs.

## Why it takes seams rather than building them

Nothing here imports an adapter. The loop drives whatever `Keeper`,
`Control` and `Acquisition` it is handed, so a test drives all three with
doubles and no beamline, and `__main__` is the one place a concrete one
is named. This module is not core, because no procedure is composed in
it, and it is held to the core's rule anyway by
`tests/test_the_core_names_no_seam.py`: a loop that imported the HTTP
adapter would work perfectly and would be a loop only one transport could
ever use.

## One policy for everything that goes wrong

Anything raised between asking and finishing is said out loud, waited
out, and then tried again. There is deliberately no classification of
which failures are worth retrying.

A conductor is a daemon at a beamline, started by a service manager that
would restart it anyway. So exiting on a refusal it judged permanent
buys a crash loop in place of a retry loop, with the log spread over
process lifetimes instead of gathered in one. A conductor whose grant was
never made says so every few seconds until somebody fixes the grant, and
then carries on without being restarted. That is the better of the two,
and it is the whole reason this catches broadly rather than carefully.

The cost is real and worth naming: a bug in an adapter is caught by the
same arm as an unreachable keeper, and shows up as a line in a log rather
than a stack trace. What makes that tolerable is that the line carries
the exception's own type and message.

## What it does not do when a report fails mid-walk

Nothing. A `conduct` whose reporting seam raised stops the walk and never
sends its ending, so the execution stays open at the keeper. That is the
accurate record rather than a gap in one: a driver that cannot report is
a driver that has effectively died, and `seams.Keeper` says an execution
left open is exactly how that looks. Reaching for a closing call on the
way out would be asserting an orderly ending over a connection that just
proved it does not work.

## Head of line, and the one case it blocks

`take` asks for a single execution. An assignment this conductor cannot
walk, because the keeper dispatched a step kind or a scope grammar it does not
know, is not claimed and not ended, so the next `take` returns it again
and the loop backs off each time. Work dispatched after it is answered
first, because the listing is newest first, so the block clears as soon
as anything else arrives and is permanent only for work already older
than the one that cannot be walked.

Claiming it and ending it would clear the block, and is refused. There is
no way to report why: the step report carries `Broken`, which means a
seam raised, and no seam ran. Writing that would put a false account of
what happened into the permanent record to unstick a queue, which is the
trade this package refuses everywhere else.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Final

from conductor.claims import Ledger
from conductor.conduct import Walk, conduct, reports_to
from conductor.seams import Citation

if TYPE_CHECKING:
    from collections.abc import Callable

    from conductor.seams import Acquisition, Assignment, Control, Keeper

DEFAULT_WAIT_SECONDS: Final = 30.0
"""How long one request to the keeper may be held open before it answers empty.

A bound on the socket rather than on anybody's patience. Connections held
open indefinitely die in proxies and NAT tables without telling either
end, so the request comes back empty at the ceiling and the loop opens
another. Nothing is lost in the gap: a dispatch landing there is sitting
at `Dispatched` and the next request returns it.

Under the keeper's own ceiling, which refuses a longer ask.
"""

DEFAULT_BACKOFF_SECONDS: Final = 5.0
"""How long to wait after something went wrong before asking again.

Short enough that a beamline is driving again promptly once the keeper comes
back, long enough that a conductor whose token was never granted is not
a request every millisecond for as long as nobody notices.
"""


def serve(
    keeper: Keeper,
    beamline: str,
    *,
    control: Control,
    acquisition: Acquisition,
    wait: float = DEFAULT_WAIT_SECONDS,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    ledger: Ledger | None = None,
    keep_going: Callable[[], bool] = lambda: True,
    pause: Callable[[float], None] = time.sleep,
    note: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> None:
    """Drive whatever the keeper dispatches to one beamline, until told to stop.

    `keep_going` is asked before each turn, which is how a signal handler
    stops this and how a test bounds it. It is checked rather than
    watched, so a stop lands after the walk in progress finishes rather
    than in the middle of one: a conductor that dropped a procedure
    half-walked would leave hardware wherever the last step put it.

    `ledger` is taken rather than made so that two conductors in one
    process share one, which is what makes a claim mean anything between
    them. One made here is right for the ordinary case of a process that
    walks one procedure at a time.

    `pause` and `note` are parameters because a test asserting on a
    backoff should not spend it, and because where a daemon's messages go
    is a deployment's choice. This package still has no logging, and a
    callable is the smallest thing that does not decide the question.
    """
    book = ledger if ledger is not None else Ledger()
    note(f"asking for work at {beamline}")

    while keep_going():
        try:
            assignment = keeper.take(beamline, wait)
            if assignment is None:
                continue
            if not keeper.claim(assignment.execution_id):
                note(f"{assignment.execution_id}: another conductor claimed it first")
                continue
            note(f"{assignment.execution_id}: walking {assignment.procedure.name}")
            walk = _walk(
                assignment, keeper=keeper, control=control, acquisition=acquisition, book=book
            )
            note(f"{assignment.execution_id}: {_tallied(walk)}")
        except Exception as problem:
            note(f"{type(problem).__name__}: {problem}")
            pause(backoff)

    note(f"stopped asking for work at {beamline}")


def _walk(
    assignment: Assignment,
    *,
    keeper: Keeper,
    control: Control,
    acquisition: Acquisition,
    book: Ledger,
) -> Walk:
    """Walk one assignment, reporting against the execution it names.

    The binding is built here and nowhere else, which is what stops a
    walk reporting against a record it is not walking.

    The citations are built here for the same reason and from the same
    two facts. An assignment's `step_ids` are index-aligned with its
    procedure's steps, so pairing each with the execution id is what
    gives every acquisition the keeper's two ids it carries into the engine's
    record. `conduct` refuses a list of the wrong length rather than
    zipping to the shorter one.
    """
    return conduct(
        assignment.procedure,
        control=control,
        acquisition=acquisition,
        ledger=book,
        reporting=reports_to(keeper, assignment.execution_id),
        cites=[
            Citation(execution_id=assignment.execution_id, step_id=step_id)
            for step_id in assignment.step_ids
        ],
    )


def _tallied(walk: Walk) -> str:
    """How a walk went, in one line, for whoever is reading the log.

    A second account of what the keeper already has, and only for a person. The
    reports went out step by step as the walk happened, so this is the
    copy that may be lost without losing anything.
    """
    return ", ".join(f"{name} {count}" for name, count in sorted(walk.tally().items()))


__all__ = ["DEFAULT_BACKOFF_SECONDS", "DEFAULT_WAIT_SECONDS", "serve"]
