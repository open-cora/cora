"""Which records this conductor may write to, and a seam that holds it to them.

A conductor is handed record names by whatever dispatched the work, and the
control seam writes them. Nothing between the two asks whether this
deployment had any business moving that record. At a beamline running real
hardware, the only thing standing between a dispatched procedure and a motor
somebody is using is that nobody dispatched one, which is a rule kept in a
person's memory rather than by anything here.

The engine seam never had that gap. An engine is configured with a prefix,
`infra/sim/install.sh` refuses a prefix that already answers, and pointing a
deployment at a station's real acquisition server is a deliberate edit of one
setting. This is the same guarantee for the other seam, which is the one a
step names directly.

## Why nothing is writable by default

An empty confinement refuses every set. That is the useful default rather
than the comfortable one: a configuration that forgot to say what may be
written looks exactly like one at a beamline with nothing to write, and
reading both as "everything" turns an omission into a conductor that can
drive hardware. A deployment says what it may touch, or it touches nothing.

## Why a refusal is raised rather than reported

`conduct` turns a seam that raised into `Broke`, which stops the walk there
and records every later step as skipped. So a procedure aimed at the wrong
beamline stops at its first misdirected write rather than working through
the rest of the list, and the steps that did run are recorded as what they
were.

The alternative was refusing the whole assignment before walking it, and it
is worse for the reason a beamline with no engine gives: it would leave the
steps that were permitted unwalked and the record saying nothing about how
far anything got.

This does not distinguish a procedure aimed at the wrong beamline from a
mistyped record, and it is worth being plain that it cannot. What it buys is
that the write does not happen.

## Why scopes rather than a prefix test

`Scope` already draws the distinction a string comparison cannot: `2bmb:m1`
and `2bmb:m10` are two motors, so a record covers itself alone, while a
namespace written with its trailing separator covers everything beneath it.
`claims` makes that argument at length. Reusing it means what may be written
and what may be claimed agree on the word covers, rather than drifting apart
in two places that never meet.

## What this is not

It is not access control. This lives in one process and binds that process.
Anything else that can reach the control system can still write, and the
thing that would refuse a write at the far end is that system's own access
security, which is never exercised by a conductor writing to records this
system serves itself.

It also permits nothing on the way in. The seam carries no read, so there is
nothing here to allow or refuse, and measuring what a host can reach is done
with the control system's own tools and moves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from conductor.claims import Scope

if TYPE_CHECKING:
    from conductor.seams import Adjusting


class OutsideConfinementError(RuntimeError):
    """A step named a record this deployment was not given to write.

    Carries the scopes as well as the record, because the two failures
    behind this read alike and want different answers: a conductor
    confined to the wrong thing, and one confined to nothing because its
    configuration never said.
    """

    def __init__(self, *, record: str, writable: frozenset[Scope]) -> None:
        self.record = record
        self.writable = writable
        if writable:
            allowed = ", ".join(sorted(str(scope) for scope in writable))
            super().__init__(
                f"this conductor may not write to {record!r}. It is confined to {allowed}"
            )
        else:
            super().__init__(
                f"this conductor may not write to {record!r}, nor to anything else: "
                "no writable scopes are configured. Name what this deployment may "
                "set under [control] in the configuration."
            )


@dataclass(frozen=True, slots=True)
class Confinement:
    """A control seam that writes only where a deployment said it may.

    Wraps another seam rather than being consulted by the walk, so that
    `conduct` has nothing to remember to ask and a deployment that forgets
    to wrap one is a change at the entrypoint rather than a check that
    silently stopped running.
    """

    adjusting: Adjusting
    writable: frozenset[Scope]

    @classmethod
    def around(cls, adjusting: Adjusting, *names: str) -> Self:
        """Build from configuration, where scopes arrive as strings."""
        return cls(adjusting=adjusting, writable=frozenset(Scope.parse(name) for name in names))

    def permits(self, record: str) -> bool:
        """Whether a write to that record would be carried out.

        A field suffix is dropped on the way in, which `Scope` does and
        this relies on: a deployment permitted to set a motor is permitted
        to set its fields, and one that was not cannot reach it through
        `.VAL` because the confinement never sees the suffix.
        """
        asked = Scope.record(record)
        return any(scope.covers(asked) for scope in self.writable)

    def set(self, record: str, value: float) -> None:
        """Write, if this deployment may write there."""
        if not self.permits(record):
            raise OutsideConfinementError(record=record, writable=self.writable)
        self.adjusting.set(record, value)


__all__ = ["Confinement", "OutsideConfinementError"]
