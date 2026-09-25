"""The acquisition seam reads both names back out of what the engine published.

The engine here is a double, and what it imitates is not guesswork: every
behaviour it has was measured against a real RunEngine by a spike, which
subscribed to a scan, read the run uid and the exit status off the
documents, and confirmed that keyword arguments of the call arrive in the
start document unchanged.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from conductor.adapters.bluesky_acquisition import (
    AROC_EXECUTION_KEY,
    AROC_STEP_KEY,
    BlueskyAcquisition,
    ManyRunsError,
    PlanRaisedError,
    UnknownPlanError,
)
from conductor.claims import Claim
from conductor.conduct import conduct
from conductor.procedure import Acquire, Procedure
from conductor.seams import Citation, ReferenceNotCarriedError
from tests._fakes import RecordingControl

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

Document = dict[str, Any]

CITES = Citation(execution_id="an-execution", step_id="a-step")
"""AROC's ids for one dispatched acquisition, as a driver would pass them."""


@dataclass(slots=True)
class FakeEngine:
    """A RunEngine's shape, and only the parts this adapter uses.

    `carries` and `drops` are the knobs that are not imitation but
    hazard: an engine that dropped the metadata it was given, or kept
    half of it, is the failure the reference check exists for, and no
    real engine will do either on request.
    """

    uids: tuple[str, ...] = ("engine-uid",)
    exit_status: str | None = "success"
    carries: bool = True
    drops: str | None = None
    """One metadata key to leave out, for the engine that keeps only half."""
    raises: BaseException | None = None
    calls: list[tuple[object, Document]] = field(default_factory=list[tuple[object, Document]])
    live: set[int] = field(default_factory=set[int])
    _subscribers: dict[int, Callable[[str, Mapping[str, Any]], None]] = field(
        default_factory=dict[int, "Callable[[str, Mapping[str, Any]], None]"]
    )
    _issued: int = 0

    def subscribe(self, func: Callable[[str, Mapping[str, Any]], None]) -> int:
        self._issued += 1
        self._subscribers[self._issued] = func
        self.live.add(self._issued)
        return self._issued

    def unsubscribe(self, token: int) -> None:
        self._subscribers.pop(token, None)
        self.live.discard(token)

    def __call__(self, plan: object, **metadata: Any) -> object:
        self.calls.append((plan, dict(metadata)))
        for uid in self.uids:
            start: Document = {"uid": uid}
            if self.carries:
                start.update({k: v for k, v in metadata.items() if k != self.drops})
            self._publish("start", start)
        if self.raises is not None:
            raise self.raises
        if self.exit_status is not None:
            for uid in self.uids:
                self._publish("stop", {"run_start": uid, "exit_status": self.exit_status})
        return tuple(self.uids)

    def _publish(self, name: str, document: Document) -> None:
        for func in list(self._subscribers.values()):
            func(name, document)


def _plan(**parameters: object) -> dict[str, object]:
    """Stand in for a routine: returns what it was given, as a plan would not."""
    return dict(parameters)


def _adapter(engine: FakeEngine) -> BlueskyAcquisition:
    return BlueskyAcquisition(engine=engine, plans={"tomo_scan": _plan})


def test_the_two_keys_are_spelled_the_way_the_reporter_reads_them() -> None:
    """A wire format written out in two projects that share no code.

    `AROC_METADATA_KEYS` in `apps/reporter` holds the same pair, and
    `docs/reference/client-contract.md` holds the agreement. Asserting
    the constants against each other elsewhere in this file proves only
    that one name is used consistently; this is the line that fails if
    somebody changes what that name means, which would go out as a
    conductor writing keys the reporter does not read and a beamline
    whose runs quietly stop being attributed.
    """
    assert (AROC_EXECUTION_KEY, AROC_STEP_KEY) == ("aroc_execution_id", "aroc_step_id")


def test_acquire_puts_arocs_two_ids_in_the_engines_metadata() -> None:
    """Both keys, and nothing else, in the start document."""
    engine = FakeEngine()
    _adapter(engine).acquire("tomo_scan", {}, CITES)
    _, metadata = engine.calls[0]
    assert metadata == {
        AROC_EXECUTION_KEY: "an-execution",
        AROC_STEP_KEY: "a-step",
    }


def test_acquire_returns_the_engine_uid_as_the_reference_to_join_on() -> None:
    acquired = _adapter(FakeEngine(uids=("c40e",))).acquire("tomo_scan", {}, CITES)
    assert acquired.engine_reference == "c40e"


def test_acquire_returns_the_ids_the_start_document_carried() -> None:
    """Read back out of the record rather than echoed.

    Echoing would make `conduct`'s comparison compare a value to itself,
    which passes for every engine including one that recorded nothing.
    """
    acquired = _adapter(FakeEngine()).acquire("tomo_scan", {}, CITES)
    assert acquired.cites == CITES


def test_acquire_an_engine_that_dropped_the_reference_answers_with_nothing() -> None:
    """The read-back is a reading, not an echo, and this is what proves it.

    An adapter that returned its argument would pass every other check
    here and this one would still fail, which is the only reason it is
    worth a separate test.
    """
    acquired = _adapter(FakeEngine(carries=False)).acquire("tomo_scan", {}, CITES)
    assert acquired.cites is None


def test_acquire_says_what_the_stop_document_said() -> None:
    acquired = _adapter(FakeEngine(exit_status="abort")).acquire("tomo_scan", {}, CITES)
    assert acquired.said == "abort"


def test_acquire_passes_a_steps_parameters_to_the_plan() -> None:
    engine = FakeEngine()
    _adapter(engine).acquire("tomo_scan", {"points": 6}, CITES)
    routine, _ = engine.calls[0]
    assert routine == {"points": 6}


def test_acquire_an_engine_that_kept_one_key_and_dropped_the_other_answers_with_nothing() -> None:
    """Both or neither, which is the rule the reporter reads by.

    A run carrying only its execution id is one that reporter treats as
    hand-run, so returning half a citation here would let the comparison
    in `conduct` pass on a record that had already lost what it was for.
    """
    engine = FakeEngine(drops=AROC_STEP_KEY)

    acquired = _adapter(engine).acquire("tomo_scan", {}, CITES)

    assert acquired.cites is None


def test_acquire_a_plan_that_opened_no_run_has_no_reference_to_join_on() -> None:
    """Nothing was recorded, so there is nothing to have dropped.

    What was passed in comes back, which keeps `conduct`'s check quiet
    about a step that never opened a record for it to look in.
    """
    acquired = _adapter(FakeEngine(uids=())).acquire("tomo_scan", {}, CITES)
    assert (acquired.engine_reference, acquired.cites) == (None, CITES)


def test_acquire_outside_a_dispatch_writes_no_aroc_keys_at_all() -> None:
    """A procedure run from a terminal belongs to no execution.

    Whatever watches this engine then reads a hand-run scan, which is
    what it was, rather than a reference to a step nothing dispatched.
    """
    engine = FakeEngine()

    acquired = _adapter(engine).acquire("tomo_scan", {}, None)

    assert engine.calls[0][1] == {}
    assert acquired.cites is None


def test_acquire_a_plan_that_opened_two_runs_is_refused() -> None:
    engine = FakeEngine(uids=("first", "second"))
    with pytest.raises(ManyRunsError) as refusal:
        _adapter(engine).acquire("tomo_scan", {}, CITES)
    assert refusal.value.uids == ("first", "second")


def test_acquire_a_plan_this_deployment_was_not_given_is_refused() -> None:
    with pytest.raises(UnknownPlanError) as refusal:
        _adapter(FakeEngine()).acquire("fly_scan", {}, CITES)
    assert refusal.value.known == ("tomo_scan",)


def test_acquire_a_plan_that_raised_after_opening_names_the_run_it_opened() -> None:
    engine = FakeEngine(uids=("c40e",), raises=RuntimeError("the detector fell over"))
    with pytest.raises(PlanRaisedError) as broke:
        _adapter(engine).acquire("tomo_scan", {}, CITES)
    assert broke.value.uid == "c40e"
    assert "the detector fell over" in str(broke.value)


def test_acquire_a_plan_that_raised_before_opening_is_left_alone() -> None:
    """Nothing to add, so nothing is wrapped and the original type survives."""
    engine = FakeEngine(uids=(), raises=TimeoutError("the engine never started"))
    with pytest.raises(TimeoutError):
        _adapter(engine).acquire("tomo_scan", {}, CITES)


def test_acquire_unsubscribes_from_an_engine_whose_plan_raised() -> None:
    """A subscription left behind would collect every later step's documents."""
    engine = FakeEngine(raises=RuntimeError("stopped"))
    with pytest.raises(Exception, match="stopped"):
        _adapter(engine).acquire("tomo_scan", {}, CITES)
    assert engine.live == set()


def test_acquire_unsubscribes_from_an_engine_whose_plan_finished() -> None:
    engine = FakeEngine()
    _adapter(engine).acquire("tomo_scan", {}, CITES)
    assert engine.live == set()


def test_walk_over_an_engine_that_drops_arocs_ids_refuses_the_step() -> None:
    """The adapter reports, `conduct` judges, and this is the two together."""
    procedure = Procedure(
        name="scan_once",
        steps=(Acquire(plan="tomo_scan", claim=Claim.over("2bmb:m1")),),
    )
    walk = conduct(
        procedure,
        control=RecordingControl(),
        acquisition=_adapter(FakeEngine(carries=False)),
        cites=[CITES],
    )
    assert not walk.finished
    assert walk.tally() == {"Broke": 1}
    assert ReferenceNotCarriedError.__name__ in str(walk.outcomes[0])


def test_the_adapter_imports_no_outside_library() -> None:
    """Its docstring says it costs no dependency, and that is checkable.

    Every other adapter here imports the library of one outside system.
    This one gets a RunEngine handed to it, so a `bluesky` import
    appearing later would be a real change rather than a tidy-up, and
    would quietly make composing an acquisition need the package.
    """
    module = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "conductor"
        / "adapters"
        / "bluesky_acquisition.py"
    )
    roots: set[str] = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    outsiders = sorted(r for r in roots if r not in sys.stdlib_module_names and r != "conductor")
    assert not outsiders, f"bluesky_acquisition.py now imports {outsiders}"
