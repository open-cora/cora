"""Ask the keeper for a question, take it up, think it, and ask again.

The loop that turns this package from a command into a process. Nothing
dispatches to a thinker: the keeper holds the question somebody put, and
a thinker is what goes looking. Four moves in a fixed order, forever.

    take     hold one request open until a question nobody has taken up
             is there
    claim    say this thinker has it, or find out it lost
    think    read the execution, conclude, and write the conclusion down
    repeat

## Why this is not in `think`

A thinking is of one question and ends. This does not end, and between
two thinkings it is doing the one thing a thinking must never do, which
is looking for more work. Keeping them apart is also what lets `think`
be handed three seams rather than five: the loop holds taking and
claiming and gives a thinking the three it needs.

The split is older than the loop. `think` could already not open a
question or claim one, and this is the caller that argument was waiting
for.

## Why it takes seams rather than building them

Nothing here imports an adapter. The loop drives whatever `Seeking`,
`Questioning`, `Observing`, `Advising` and `Concluding` it is handed, so
a test drives all of them with doubles and no keeper, and `__main__` is
the one place a concrete one is named. This module is not core, because
no thinking is composed in it, and it is held to the core's rule anyway
by `tests/test_the_core_names_no_seam.py`: a loop that imported the HTTP
adapter would work perfectly and would be a loop only one transport
could ever use.

## One policy for everything that goes wrong

Anything raised between asking and finishing is said out loud, waited
out, and then tried again. There is deliberately no classification of
which failures are worth retrying.

A thinker running this way is a daemon, started by a service manager
that would restart it anyway. So exiting on a refusal it judged
permanent buys a crash loop in place of a retry loop, with the log
spread over process lifetimes instead of gathered in one. A thinker
whose grant was never made says so every few seconds until somebody
fixes the grant, and then carries on without being restarted.

The cost is real and worth naming: a bug in an adapter is caught by the
same arm as an unreachable keeper, and shows up as a line in a log
rather than a stack trace. What makes that tolerable is that the line
carries the exception's own type and message.

**This does not turn a failure into a conclusion, and that rule is
untouched.** A provider that raised is caught here and retried, never
recorded: nothing reaches the inquiry, so a thinker that could not think
stays a question nobody has answered. Writing `Abstain` instead would
put a finding into the world that nothing found, which is the failure
the four conclusions are four classes wide to avoid. What changes when a
thinker runs as a process is only who tries again.

## A lost claim is not a failure and not the end

`claim` answering False means another thinker holds the question or one
has already answered it. Run once from a command line that ends the run,
because there is nothing else to do and somebody is standing there. Here
it is the next turn of the loop: the race is ordinary, the work is
somebody else's, and there may be another question behind it.

The head of the queue does not block on it either, because the claim is
what moved: a question this thinker lost has been taken up at the keeper,
which is not a status the next ask asks for.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Final

from thinker.think import think

if TYPE_CHECKING:
    from collections.abc import Callable

    from thinker.seams import Advising, Concluding, Observing, Questioning, Seeking

DEFAULT_WAIT_SECONDS: Final = 30.0
"""How long one request to the keeper may be held open before it answers empty.

A bound on the socket rather than on anybody's patience. Connections held
open indefinitely die in proxies and NAT tables without telling either
end, so the request comes back empty at the ceiling and the loop opens
another. Nothing is lost in the gap: a question landing there is sitting
at `Open` and the next request returns it.

Under the keeper's own ceiling, which refuses a longer ask.
"""

DEFAULT_BACKOFF_SECONDS: Final = 5.0
"""How long to wait after something went wrong before asking again.

Short enough that questions are answered promptly once the keeper comes
back, long enough that a thinker whose token was never granted is not a
request every millisecond for as long as nobody notices.
"""


def serve(
    seeking: Seeking,
    *,
    questioning: Questioning,
    observing: Observing,
    advising: Advising,
    concluding: Concluding,
    wait: float = DEFAULT_WAIT_SECONDS,
    backoff: float = DEFAULT_BACKOFF_SECONDS,
    keep_going: Callable[[], bool] = lambda: True,
    pause: Callable[[float], None] = time.sleep,
    note: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> None:
    """Answer whatever questions the keeper is holding, until told to stop.

    `keep_going` is asked before each turn, which is how a signal handler
    stops this and how a test bounds it. It is checked rather than
    watched, so a stop lands after the thinking in progress finishes
    rather than in the middle of one: a thinker that dropped a question
    half-answered would leave it claimed with nothing on it, which is
    the shape this system reads as an abandoned thinker.

    `pause` and `note` are parameters because a test asserting on a
    backoff should not spend it, and because where a daemon's messages
    go is a deployment's choice. This package has no logging, and a
    callable is the smallest thing that does not decide the question.

    Nothing is printed of what was concluded beyond the word. The
    conclusion, the boundary it was drawn from and the proposal all
    reach the inquiry, so unlike the one-shot path there is no reader
    standing here for whom this is the only copy.
    """
    note("asking for questions to answer")

    while keep_going():
        try:
            question = seeking.take(wait)
            if question is None:
                continue
            if not questioning.claim(question.inquiry_id):
                note(f"{question.inquiry_id}: another thinker claimed it first")
                continue
            note(f"{question.inquiry_id}: thinking about {question.execution_id}")
            thought = think(
                question,
                observing=observing,
                advising=advising,
                concluding=concluding,
            )
            note(f"{question.inquiry_id}: {type(thought.conclusion).__name__.lower()}")
        except Exception as problem:
            note(f"{type(problem).__name__}: {problem}")
            pause(backoff)

    note("stopped asking for questions to answer")


__all__ = ["DEFAULT_BACKOFF_SECONDS", "DEFAULT_WAIT_SECONDS", "serve"]
