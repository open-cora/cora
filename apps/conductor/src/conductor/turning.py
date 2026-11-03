"""Turning a pursuit: the port a driver needs, and what one pass does.

A pursuit is a standing authorization that advances a round at a time. It
observes an execution, puts a question about it, and when the answer comes
back it acts on it and dispatches whatever that answer proposed. The record
holds all of that. Nothing in the record drives it, deliberately: something
outside notices that an execution ended and calls in, the way the work
intake notices that one was dispatched.

This is that something, split the way everything else here is split. The
Protocol says what a driver needs of the record; `turn_once` says what one
pass does with it; neither knows how either reaches the other.

## Why a pass carries no state

The thing driving a pursuit has to survive being restarted and being
duplicated. That is not a nicety: the record refuses a second round about
one execution, which is what makes a crashed driver safe to bring back,
and the guarantee is worth nothing if the driver has to remember where it
got to in order to use it.

So a pass reads a pursuit and decides from what it reads. An open round is
one whose outcome is not set, which the record now says out loud. The
executions a pursuit has already asked about are the ones its rounds name.
Both come off the same read, so two drivers looking at one pursuit reach
the same conclusion, and the loser of any race is refused by the record
rather than by anything arranged here.

## Why it closes before it opens

A pursuit asks one question at a time. A pass that opened a second round
while the first was unanswered would have two questions outstanding about
one goal, and the budget counts rounds, so it would also spend twice as
fast as the loop it was authorizing. Closing first is what keeps the loop
sequential without anything having to hold a lock.

## What it does not decide

Whether to go on. Only the record knows that: closing a round on an
advancing answer leaves the pursuit running and dispatches work, and every
other answer stops it or holds it. A pass reports what the close came to
and asks again next time, which is why nothing here reads a budget or a
status beyond the listing that produced the pursuit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class Round:
    """One turn of a pursuit's loop, as a driver reads it.

    `outcome` is unset while the round is waiting on an answer, and that
    is the whole of how a driver tells where the loop is. A count of
    rounds cannot tell a question still outstanding from one already
    acted on, because both leave the pursuit running.
    """

    index: int
    execution_id: str
    inquiry_id: str
    outcome: str | None = None

    @property
    def is_open(self) -> bool:
        """Whether this round is still waiting on an answer."""
        return self.outcome is None


@dataclass(frozen=True, slots=True)
class Pursuit:
    """One authorization, in as much of it as a driver needs.

    Not the goal, the scopes or the budget. A driver states none of them
    and may not: they are read off the record when a round closes, by the
    handler that applies them. Carrying them here would be a copy of a
    permission, which is the one thing this process must not hold.
    """

    pursuit_id: str
    beamline: str
    rounds: tuple[Round, ...] = ()


@dataclass(frozen=True, slots=True)
class Closed:
    """What closing a round came to, as the record reports it."""

    outcome: str
    dispatched_id: str | None = None


@runtime_checkable
class Turning(Protocol):
    """Reading pursuits and moving them on, over whatever reaches the record."""

    def pursuits(self) -> Sequence[Pursuit]:
        """Every pursuit still authorized to advance, with its rounds."""
        ...

    def ended(self, beamline: str) -> Sequence[str]:
        """Executions at one beamline that have finished, oldest first.

        Oldest first because a pursuit observes what happened in the order
        it happened. A newest-first listing would have a busy beamline
        advance on its most recent scan and never reach the one before.
        """
        ...

    def answered(self, inquiry_id: str) -> bool:
        """Whether a thinker has concluded on this inquiry yet."""
        ...

    def open_round(self, pursuit_id: str, execution_id: str) -> str | None:
        """Ask about one execution, and say which inquiry carries the question.

        `None` where the record refused because this pursuit has already
        asked about that execution. That is the retry guard working rather
        than a fault, and it is what a second driver sees when it loses a
        race it did not know it was in.
        """
        ...

    def close_round(self, pursuit_id: str, index: int) -> Closed:
        """Read the answer, act on it, and end the round."""
        ...


@dataclass(frozen=True, slots=True)
class Opened:
    """A question was put about an execution nothing had asked about."""

    pursuit_id: str
    execution_id: str
    inquiry_id: str


@dataclass(frozen=True, slots=True)
class Settled:
    """An answer came back and the record acted on it."""

    pursuit_id: str
    index: int
    outcome: str
    dispatched_id: str | None = None


@dataclass(frozen=True, slots=True)
class Waited:
    """A question is outstanding and no thinker has answered it yet."""

    pursuit_id: str
    inquiry_id: str


@dataclass(frozen=True, slots=True)
class Idled:
    """Nothing to ask about: every ended execution has been observed."""

    pursuit_id: str


Turn = Opened | Settled | Waited | Idled
"""What one pass over one pursuit did.

Four outcomes and not a boolean, because a caller logging this wants to
tell a loop that is waiting on a thinker from one that has run out of
work. Both are quiet and only one of them will move again on its own.
"""


def turn_once(turning: Turning, pursuit: Pursuit) -> Turn:
    """Move one pursuit on by at most one step.

    Closes an outstanding round when its answer has landed, and otherwise
    asks about the oldest ended execution this pursuit has not asked
    about. Does nothing else, and in particular does not loop: a caller
    that wants the pursuit driven to a standstill calls again, which is
    also what a caller that crashed does when it comes back.
    """
    waiting = next((turn for turn in pursuit.rounds if turn.is_open), None)
    if waiting is not None:
        if not turning.answered(waiting.inquiry_id):
            return Waited(pursuit_id=pursuit.pursuit_id, inquiry_id=waiting.inquiry_id)
        closed = turning.close_round(pursuit.pursuit_id, waiting.index)
        return Settled(
            pursuit_id=pursuit.pursuit_id,
            index=waiting.index,
            outcome=closed.outcome,
            dispatched_id=closed.dispatched_id,
        )

    observed = {turn.execution_id for turn in pursuit.rounds}
    for execution_id in turning.ended(pursuit.beamline):
        if execution_id in observed:
            continue
        inquiry_id = turning.open_round(pursuit.pursuit_id, execution_id)
        if inquiry_id is None:
            continue
        return Opened(
            pursuit_id=pursuit.pursuit_id,
            execution_id=execution_id,
            inquiry_id=inquiry_id,
        )
    return Idled(pursuit_id=pursuit.pursuit_id)


__all__ = [
    "Closed",
    "Idled",
    "Opened",
    "Pursuit",
    "Round",
    "Settled",
    "Turn",
    "Turning",
    "Waited",
    "turn_once",
]
