"""The two outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which control
library and which acquisition engine a deployment runs is a choice it
makes at its entrypoint. That is the same arrangement `apps/reporter` uses
for a store, and the reason is the same: a beamline runs what it runs, and
a package that named one would be holding an opinion a deployment owns.

Neither Protocol carries a `Port` suffix. Everything in this module is a
seam, so saying so distinguishes nothing, and `apps/api` forbids the
suffix for that reason.

## Why control has two writing verbs rather than one

A beamline is not all motors. `spikes/tomoscan_adapter/` reads an engine
whose configuration surface is `mbbo` enumerations, `stringout` names and
256-byte `UCHAR` waveforms, and not one of them is a number that travels
to a position.

Widening one verb to carry those costs more than it looks. `move`
promises that a record arrived and stopped, and an adapter earns that
promise from `.RBV`, `.RDBD` and `.DMOV`, which are motor-record fields.
A record serving none of them cannot be checked that way, so a single
verb would weaken its promise according to whichever record it was
handed, and the weakening would be invisible at the call site. That is
the shape of failure this package exists to refuse:
`spikes/conductor/FINDINGS.md` measured a held motor accepting every
move, performing none, and reporting success throughout.

So there are two verbs and two promises. `move` is motion, verified to
rest. `set` is a value, verified by reading the record back. The author
of a step picks the promise the step needs, and an adapter asked for one
it cannot keep raises rather than quietly delivering the other.

## Why an acquisition is bounded by its step

`Control` has three clocks and `Acquisition` had none, so a scan that
hung hung the walk. The bound sits on the step rather than on the
adapter because the knowledge is the author's: a tomography fly scan is
twenty minutes and an alignment is thirty seconds, and one number
configured per engine cannot be right for both.

What a bound is not is a promise every engine can keep. A bare RunEngine
runs a plan in the calling thread, so nothing inside `acquire` can
interrupt it, while an adapter polling Channel Access may give up
whenever it likes. An adapter handed a bound it cannot enforce is
required to refuse, for the same reason the reference check exists: a
seam that took the argument and ignored it would report `Done` on a step
whose bound never applied, and nothing downstream could tell.

## Why acquisition returns what the engine said, unmapped

`spikes/conductor/FINDINGS.md` drove four collisions into a real scan and
every one of them ended `exit_status: "success"`, including a six-point
scan that took four of its readings at one position. So an engine's word
for how a run ended is a claim this system was given, not a fact it
checked, and a seam that turned `success` into a boolean here would be
laundering the claim into a conclusion one layer before anyone could see
it. The word travels verbatim and something further out decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

Setting = float | int | str
"""What one record can be sent to, or read back as.

Three types, because Channel Access serves three kinds of thing a
procedure needs to write: a number, an enumeration and text. `int` is
named beside `float` although a type checker folds the two together,
because this alias is also used at runtime and `isinstance(1, float)` is
False.

An enumeration travels as its choice string rather than its index. That
is the vocabulary the engines use on themselves: TomoScan reads several
of its own records with `get(as_string=True)` and compares the result to
a literal, so a procedure written in indices would be written in a
vocabulary nothing else in the deployment shares. It is also the half
that survives a database edit, since inserting a choice renumbers every
index after it and renames nothing.
"""


@dataclass(frozen=True, slots=True)
class Acquired:
    """What came back from asking an engine to run something.

    `engine_reference` is the name that joins. A reporter watching the
    same engine records its runs under the engine's own name for them, so
    that is what AROC can be asked for later, and
    `docs/reference/client-contract.md` holds both halves of that
    agreement. It is optional because not every engine has a name to
    give, and because a plan that opened no run has nothing to be named.

    `reference` is this conductor's own, minted before the request went
    out and carried into the engine's record: a bare RunEngine hands a
    caller nothing at submit time but copies metadata it is given
    verbatim into the start document. It is not the join. It puts this
    conductor's name on the engine's own permanent record, where a person
    reading a data catalogue can find it, and an adapter that reads it
    back out is what gives the check below something real to compare.
    """

    reference: str
    engine_reference: str | None
    said: str


class ReferenceNotCarriedError(RuntimeError):
    """An engine answered naming a reference other than the one it was given.

    An adapter is expected to read this field back out of what the engine
    recorded rather than echo the argument it was handed, so a mismatch
    means the engine dropped the name on the way through. That matters
    even though the join runs on `engine_reference`: an engine that
    silently discards metadata is one whose record of what ran here is
    wrong, and the walk would report `Done` for every step regardless,
    which is the shape of failure this package exists to refuse. It costs
    one comparison to catch here and cannot be caught at all afterwards.
    """

    def __init__(self, *, plan: str, asked: str, got: str) -> None:
        self.plan = plan
        self.asked = asked
        self.got = got
        super().__init__(
            f"the acquisition of {plan!r} was given the reference {asked!r} "
            f"and came back with {got!r}, so nothing could find the run later"
        )


class BoundNotEnforceableError(RuntimeError):
    """A step asked for a bound the engine behind this seam cannot hold to.

    Raised by the adapter rather than by the core, because whether a
    bound can be enforced is a fact about the engine. Refused rather than
    ignored: a walk whose step declared twenty minutes and whose seam
    silently waited forever would report the same `Done` either way, and
    the difference is a beamline nobody is watching.
    """

    def __init__(self, *, plan: str, bound: float, because: str) -> None:
        self.plan = plan
        self.bound = bound
        self.because = because
        super().__init__(
            f"the acquisition of {plan!r} asked for a bound of {bound}s, which this "
            f"engine cannot enforce: {because}"
        )


@runtime_checkable
class Control(Protocol):
    """Reading and writing one record at a time, underneath any engine."""

    def move(self, record: str, value: float) -> None:
        """Send a record to a position and return once it is there and at rest.

        For a record that reports motion. An adapter that cannot confirm
        the motion finished raises rather than returning, because a
        caller that wanted only the write wanted `set`.
        """
        ...

    def set(self, record: str, value: Setting) -> None:
        """Send a record to a value and return once it reads that value back.

        For everything that is not motion: an enumeration, a name, a
        path, a count. The promise is narrower than `move` on purpose,
        and is the strongest one available for a record that reports no
        position and no motion.
        """
        ...

    def read(self, record: str) -> Setting:
        """Read a record now, as whichever of the three types it serves.

        A caller that knows it asked for a number still has to narrow the
        answer. That is the cost of one read verb over a pair of them,
        and it is paid at the few call sites that read rather than in
        every adapter.
        """
        ...


@runtime_checkable
class Acquisition(Protocol):
    """Asking an engine to run a routine, and hearing how it went."""

    def acquire(
        self,
        plan: str,
        parameters: Mapping[str, object],
        reference: str,
        bound: float | None,
    ) -> Acquired:
        """Run a plan, carrying `reference` so the run can be found later.

        `bound` is the author's ceiling in seconds, or `None` for a step
        that declared none. An adapter that cannot enforce a bound it was
        given raises `BoundNotEnforceableError`; one given `None` waits
        as long as the engine takes.
        """
        ...
