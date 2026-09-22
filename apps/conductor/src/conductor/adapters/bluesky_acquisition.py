"""An acquisition seam over a bare RunEngine, which reads the join back out.

Two identities come out of one plan and this adapter is where they are
picked up. `spikes/conductor/FINDINGS.md` section 7 measured both against
a real engine:

    minted here        540aa3cb-1d6b-4aaa-97a1-e7f9832e376f
    in the start       540aa3cb-1d6b-4aaa-97a1-e7f9832e376f
    engine run uid     0e8d351c-ec26-4d05-ab46-51c7417b8745

The uid is the one that joins. A reporter watching the same engine files
its runs under the engine's uid, so that is the name AROC can be asked
for, and `docs/reference/client-contract.md` is where the two halves of
that are written down. The minted directive id is carried anyway, for two
reasons that are not the join: it puts this conductor's name on the
engine's own permanent record, where a person reading a data catalogue
can find it, and reading it back is what makes `conduct`'s reference
check mean something rather than compare a value to itself.

## Why the uid is taken from the start document

`RE(plan)` returns uids when the plan finishes, so the return value would
answer the same question. The start document is used instead because it
is also where the directive id is, so both halves of the join come from
one reading and cannot disagree with each other. The return value is not
read at all.

## Why this module imports nothing

Every other adapter here imports the library of the system it speaks to,
because a protocol needs an implementation. This one does not, because a
RunEngine is an object the deployment already built and hands over, and
the plans are callables it already imported. What is bluesky-specific
here is the shape of the call and the names of three document keys, not a
package. `Engine` below is that shape, written out rather than imported,
so composing this adapter costs no dependency either.

## What it refuses

A plan that opens more than one run. `Acquired` names one run and the
step that ran it claimed its devices as one step, so picking the first of
several would attach this step to a run chosen by ordering. That is the
kind of wrong answer nothing downstream could detect, which is the same
reason `conduct` checks the reference at all. A deployment that really
does run multi-run plans wants a seam that returns several, and that is a
change to `Acquisition` rather than a policy here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from conductor.seams import Acquired

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

DIRECTIVE_KEY: Final = "aroc_directive_id"
"""The start-document key this conductor's own reference travels under.

A bare RunEngine copies keyword arguments of its call into the start
document unchanged, which is what section 7 of the findings established.
The name is spelled here and in no other module.
"""

RUN_UID_KEY: Final = "uid"
"""Where a start document carries the engine's own name for the run."""

EXIT_STATUS_KEY: Final = "exit_status"
"""Where a stop document carries the engine's word for how the run ended."""


@runtime_checkable
class Engine(Protocol):
    """The three things this adapter needs of a RunEngine.

    Written out rather than imported so that this module costs no
    dependency. A real RunEngine satisfies it; so does `FakeEngine` in
    `tests/test_bluesky_acquisition.py`, which is what lets this adapter
    be checked with no engine installed.
    """

    def __call__(self, plan: Any, **metadata: Any) -> object:
        """Run a plan to completion, copying metadata into the start."""
        ...

    def subscribe(self, func: Callable[[str, Mapping[str, Any]], None]) -> int:
        """Call `func` with every document, returning a token to undo it."""
        ...

    def unsubscribe(self, token: int) -> None:
        """Stop calling whatever `token` was returned for."""
        ...


class AcquisitionError(RuntimeError):
    """Something stopped a plan from running, or from being joinable after."""


class UnknownPlanError(AcquisitionError):
    """The procedure named a plan this deployment has not been given.

    Refused rather than guessed at, for the reason the reporter refuses an
    unmapped plan name: which routine a name means is a deployment fact,
    and an adapter that picked one would attach a step to whichever plan
    it happened to find.
    """

    def __init__(self, plan: str, known: tuple[str, ...]) -> None:
        self.plan = plan
        self.known = known
        offered = ", ".join(known) if known else "nothing"
        super().__init__(f"no plan named {plan!r} was given to this adapter, which holds {offered}")


class ManyRunsError(AcquisitionError):
    """One step opened several runs, so there is no single run to join to."""

    def __init__(self, plan: str, uids: tuple[str, ...]) -> None:
        self.plan = plan
        self.uids = uids
        super().__init__(
            f"the plan {plan!r} opened {len(uids)} runs ({', '.join(uids)}), and a step "
            "names one, so which of them this step ran cannot be said"
        )


class PlanRaisedError(AcquisitionError):
    """The engine raised after opening a run, and this says which run.

    Wrapping buys one thing: the uid. A plan that fails partway has
    already published a start, so a reporter watching the same engine has
    already recorded the run, and without this the walk would report that
    a step broke while the only name for what it broke was thrown away.
    An engine that raises before opening anything is re-raised untouched,
    because there is nothing to add.
    """

    def __init__(self, plan: str, uid: str, cause: BaseException) -> None:
        self.plan = plan
        self.uid = uid
        super().__init__(
            f"the plan {plan!r} raised {type(cause).__name__}: {cause}, after opening run {uid}"
        )


@dataclass(slots=True)
class BlueskyAcquisition:
    """Runs one named plan at a time and reports what the engine recorded.

    `plans` is the deployment's map from the name a procedure uses to the
    callable that builds the routine. It is given rather than discovered
    for the same reason the reporter's plan map is configuration: which
    routine a name means depends on the installation, and nothing on a
    procedure would tell two of them apart.
    """

    engine: Engine
    plans: Mapping[str, Callable[..., Any]]

    def acquire(self, plan: str, parameters: Mapping[str, object], reference: str) -> Acquired:
        """Run a plan, and come back with both names for what ran.

        `reference` is carried into the engine's start document and read
        back out of it. What is returned in `Acquired.reference` is
        therefore what the engine recorded rather than what was passed in,
        which is the whole point: `conduct` compares the two and refuses a
        walk whose engine dropped the name.
        """
        routine = self.plans.get(plan)
        if routine is None:
            raise UnknownPlanError(plan, tuple(sorted(self.plans)))

        starts: list[Mapping[str, Any]] = []
        stops: list[Mapping[str, Any]] = []
        token = self.engine.subscribe(_collector(starts, stops))
        try:
            self.engine(routine(**parameters), **{DIRECTIVE_KEY: reference})
        except Exception as exc:
            uid = _first_uid(starts)
            if uid is None:
                raise
            raise PlanRaisedError(plan, uid, exc) from exc
        finally:
            self.engine.unsubscribe(token)

        return self._acquired(plan, starts, stops, reference)

    def _acquired(
        self,
        plan: str,
        starts: list[Mapping[str, Any]],
        stops: list[Mapping[str, Any]],
        reference: str,
    ) -> Acquired:
        """Turn what the engine published into the seam's answer.

        A plan that opened no run is not an error. Some routines move
        things and record nothing, and there is no run to join to because
        there is no run. The reference passed in is returned unchanged in
        that case, which is honest: nothing was recorded, so nothing can
        be read back, and `conduct`'s check has nothing to catch.
        """
        if len(starts) > 1:
            raise ManyRunsError(plan, tuple(_text(s.get(RUN_UID_KEY)) or "?" for s in starts))

        said = _text(stops[0].get(EXIT_STATUS_KEY)) if stops else None
        if not starts:
            return Acquired(reference=reference, engine_reference=None, said=said or "")

        start = starts[0]
        return Acquired(
            reference=_text(start.get(DIRECTIVE_KEY)) or "",
            engine_reference=_text(start.get(RUN_UID_KEY)),
            said=said or "",
        )


def _collector(
    starts: list[Mapping[str, Any]], stops: list[Mapping[str, Any]]
) -> Callable[[str, Mapping[str, Any]], None]:
    """A subscription that keeps the two document types this reads.

    Everything else is dropped where it arrives. A step may publish
    thousands of readings and none of them says anything about identity,
    so holding them would grow with the scan for no answer.
    """

    def collect(name: str, document: Mapping[str, Any]) -> None:
        if name == "start":
            starts.append(document)
        elif name == "stop":
            stops.append(document)

    return collect


def _first_uid(starts: list[Mapping[str, Any]]) -> str | None:
    """The uid of the first run opened, for an error that wants to name one."""
    return _text(starts[0].get(RUN_UID_KEY)) if starts else None


def _text(value: object) -> str | None:
    """A document value as a string, or `None` when there is nothing there.

    Documents arrive as plain dictionaries off a wire and nothing checks
    their types on the way in, so a key that should hold a uid may hold
    anything or may be absent. An empty string is treated as absent,
    because a reference that is present and blank joins to nothing and
    reads as a value.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DIRECTIVE_KEY",
    "EXIT_STATUS_KEY",
    "RUN_UID_KEY",
    "AcquisitionError",
    "BlueskyAcquisition",
    "Engine",
    "ManyRunsError",
    "PlanRaisedError",
    "UnknownPlanError",
]
