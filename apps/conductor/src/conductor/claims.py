"""Who holds which piece of the beamline, and what stops two steps sharing one.

This module exists because of a measurement rather than a principle.
A spike drove a real scan while a second process
wrote to the motor it owned, and found that every collision reported
success: the run's data was wrong, sometimes self-consistently wrong, and
nothing anywhere raised. The same write aimed at a motor the scan did not
own changed nothing at all. So the hazard is two writers on one device,
and a conductor that walks a procedure across several seams has to be the
thing that prevents it, because neither seam can see what the other holds.

## Why a claim names records and not devices

The obvious unit is the device object a startup profile builds, and a
spike measured what that costs. Two `EpicsMotor`
objects bound to one motor under two names connect at once, share no read
keys at all, and a blocking move through the second returns before the
motion starts. Two claims built from such objects are disjoint by
inspection and name the same hardware.

So a claim names what the IOC serves. That is the only vocabulary two
clients who have never met are obliged to agree on. The record's own
`DESC` field does not qualify: it is served empty, it is writable by any
client, and nothing makes it unique.

## Why coverage is not `startswith`

A record name is atomic. `2bmb:m1` and `2bmb:m10` are two motors, and a
prefix test that compared them as strings would have the first claim the
second, refusing steps that never conflicted. So a record covers itself
and nothing else.

A namespace is the other form, for the case a single device really is a
family of records: an area detector is a `2bmb:cam1:` and several dozen
records under it. A namespace covers anything beneath it, and it is
written with its trailing separator so that the two forms cannot be
confused for one another.

The separator is `:`, which is EPICS convention at the facilities this is
written for rather than anything the protocol requires. A deployment
whose names are built another way has to change `NAMESPACE_SEPARATOR` and
will find the rest of this module follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Self

if TYPE_CHECKING:
    from types import TracebackType

NAMESPACE_SEPARATOR: Final = ":"
"""What marks a scope as covering everything beneath it rather than one record."""

FIELD_SEPARATOR: Final = "."
"""What separates an EPICS record from one of its fields."""


class InvalidScopeError(ValueError):
    """A scope was empty, or was only a separator."""


@dataclass(frozen=True, slots=True)
class Scope:
    """One piece of the Channel Access namespace, claimed whole.

    Built through `record` or `namespace` when the caller knows which it
    means, and through `parse` when it is reading configuration.
    """

    name: str
    covers_beneath: bool

    @classmethod
    def record(cls, name: str) -> Self:
        """One record, and none of its neighbours.

        A field suffix is dropped, because a claim on `2bmb:m1.VAL` and a
        claim on `2bmb:m1.STOP` are a claim on the same motor twice. A
        spike showed why that has to be so: the rival writes that
        corrupted a scan went to `.VAL`, `.STOP` and `.SPMG`, and a
        claim that distinguished them would have permitted all three.
        """
        cleaned = name.strip()
        if FIELD_SEPARATOR in cleaned:
            cleaned = cleaned.split(FIELD_SEPARATOR, 1)[0]
        cleaned = cleaned.rstrip(NAMESPACE_SEPARATOR)
        if not cleaned:
            raise InvalidScopeError(f"a record scope needs a name, got {name!r}")
        return cls(name=cleaned, covers_beneath=False)

    @classmethod
    def namespace(cls, prefix: str) -> Self:
        """Everything served beneath a prefix, such as a detector's records."""
        cleaned = prefix.strip().rstrip(NAMESPACE_SEPARATOR)
        if not cleaned:
            raise InvalidScopeError(f"a namespace scope needs a prefix, got {prefix!r}")
        return cls(name=cleaned + NAMESPACE_SEPARATOR, covers_beneath=True)

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read either form, deciding from the trailing separator."""
        return (
            cls.namespace(text) if text.strip().endswith(NAMESPACE_SEPARATOR) else cls.record(text)
        )

    def covers(self, other: Scope) -> bool:
        """Whether holding this scope already holds the other."""
        if self.covers_beneath:
            return other.name == self.name or other.name.startswith(self.name)
        return other.name == self.name

    def conflicts_with(self, other: Scope) -> bool:
        """Whether two scopes cannot be held at once, in either direction."""
        return self.covers(other) or other.covers(self)

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Claim:
    """Every scope one step needs for as long as it runs."""

    scopes: frozenset[Scope]

    @classmethod
    def over(cls, *names: str) -> Self:
        """Build from configuration, where scopes arrive as strings."""
        return cls(scopes=frozenset(Scope.parse(name) for name in names))

    @classmethod
    def nothing(cls) -> Self:
        """A step that touches no device, such as one that only waits."""
        return cls(scopes=frozenset())

    def overlap(self, other: Claim) -> frozenset[Scope]:
        """The scopes of this claim that the other cannot be held alongside.

        Returns this claim's side of the collision rather than a boolean,
        because a refusal that cannot say which device was already taken
        sends its reader to compare two lists by hand.
        """
        return frozenset(
            mine
            for mine in self.scopes
            if any(mine.conflicts_with(theirs) for theirs in other.scopes)
        )

    def conflicts_with(self, other: Claim) -> bool:
        """Whether the two claims name any hardware in common."""
        return bool(self.overlap(other))

    def __str__(self) -> str:
        return ", ".join(sorted(str(scope) for scope in self.scopes)) or "nothing"


class ClaimConflictError(RuntimeError):
    """A step asked for hardware another step is still holding.

    Carries both holders and the overlapping scopes, because the useful
    question on being refused is which device and who has it, and a
    message naming only one of the three sends its reader to guess.
    """

    def __init__(self, *, holder: str, blocked: str, overlap: frozenset[Scope]) -> None:
        self.holder = holder
        self.blocked = blocked
        self.overlap = overlap
        collided = ", ".join(sorted(str(scope) for scope in overlap))
        super().__init__(f"{blocked!r} wants {collided}, which {holder!r} is holding")


@dataclass(slots=True)
class Ledger:
    """What is held right now, and the only thing that grants it.

    A ledger is deliberately not durable. It records what this conductor
    is doing at this moment, and a conductor cannot promise anything
    about the moment after it dies: a spike SIGKILLed a driver and left a
    motor moving with no stop document ever emitted. So a
    ledger that survived a restart would be claiming to know something it
    does not, and the recovery question belongs to whatever watches the
    hardware rather than to this.
    """

    _held: dict[str, Claim] = field(default_factory=dict[str, Claim])

    def held_by(self, holder: str) -> Claim | None:
        """What this holder has, if anything."""
        return self._held.get(holder)

    def holders(self) -> frozenset[str]:
        """Everyone currently holding something."""
        return frozenset(self._held)

    def acquire(self, holder: str, claim: Claim) -> None:
        """Grant a claim, or refuse it naming what stands in the way.

        A holder already in the ledger is a bug in the caller rather than
        a conflict, so it raises the same way rather than quietly
        replacing what it had.
        """
        if holder in self._held:
            raise ClaimConflictError(
                holder=holder, blocked=holder, overlap=self._held[holder].scopes
            )
        for other, existing in self._held.items():
            overlap = claim.overlap(existing)
            if overlap:
                raise ClaimConflictError(holder=other, blocked=holder, overlap=overlap)
        self._held[holder] = claim

    def release(self, holder: str) -> None:
        """Give back whatever a holder had. Releasing nothing is not an error."""
        self._held.pop(holder, None)

    def granted(self, holder: str, claim: Claim) -> _Granted:
        """Hold a claim for the duration of a block, and release it after.

        Released on the way out however the block ends, because a step
        that raised has stopped touching its devices just as surely as
        one that returned, and a ledger that kept the claim would wedge
        every later step that needed the same motor.
        """
        return _Granted(self, holder, claim)


@dataclass(slots=True)
class _Granted:
    """The context manager `Ledger.granted` returns."""

    ledger: Ledger
    holder: str
    claim: Claim

    def __enter__(self) -> Claim:
        self.ledger.acquire(self.holder, self.claim)
        return self.claim

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.ledger.release(self.holder)
