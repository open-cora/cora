"""The adapter that asks AROC for work, driven through a transport that answers.

No server here. What this adapter does is build requests and read
answers, and a real AROC standing behind it would test AROC. The routes,
their status codes and their bodies are the ones `apps/api` declares, and
the contract tier over there is what holds them to it.

The shapes below are copied from those routes rather than imported,
because the two packages share no code on purpose and a wire format one
of them could change without the other noticing is exactly the thing
worth writing out twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from conductor.adapters.keeper_http import (
    HttpKeeper,
    RequestRefusedError,
    UnwalkableAssignmentError,
)
from conductor.claims import Claim, Scope
from conductor.outcomes import Broke, Done, Outcome, Refused, Skipped
from conductor.procedure import Acquire, Move
from conductor.seams import Acquired, Citation, Keeper

if TYPE_CHECKING:
    from collections.abc import Mapping

BASE_URL = "https://keeper.example"
TOKEN = "a-conductor-token"

EXECUTION_ID = "8f1d5a6e-0b2c-4d3e-9f10-2a3b4c5d6e7f"
PROCEDURE_ID = "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"
PLAN_ID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
MOVE_STEP_ID = "aaaaaaaa-1111-4222-8333-444444444444"
ACQUIRE_STEP_ID = "bbbbbbbb-1111-4222-8333-444444444444"


@dataclass(slots=True)
class Reply:
    """One canned answer, in the shape the adapter reads an answer in."""

    status_code: int
    body: Any = None
    text: str = ""

    def json(self) -> Any:
        return self.body


@dataclass(slots=True)
class Recorded:
    """One request the adapter made, kept whole so a test can assert on any of it."""

    method: str
    path: str
    params: Mapping[str, str] | None = None
    headers: Mapping[str, str] | None = None
    json: Mapping[str, Any] | None = None
    timeout: float | None = None


@dataclass(slots=True)
class FakeHttp:
    """Answers from a table, and remembers every ask in order.

    A path with no entry raises rather than returning a default. A test
    that did not say how a route answers is a test whose subject reached
    somewhere it was not meant to, and a silent 200 would hide that.
    """

    replies: dict[str, Reply] = field(default_factory=dict[str, Reply])
    sent: list[Recorded] = field(default_factory=list[Recorded])

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Reply:
        return self._answer(
            Recorded("GET", _path(url), params=params, headers=headers, timeout=timeout)
        )

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Reply:
        return self._answer(Recorded("POST", _path(url), headers=headers, json=json))

    def _answer(self, request: Recorded) -> Reply:
        self.sent.append(request)
        reply = self.replies.get(request.path)
        if reply is None:
            raise AssertionError(
                f"nothing told this transport how to answer {request.method} {request.path}"
            )
        return reply

    def asked(self, path: str) -> list[Recorded]:
        return [request for request in self.sent if request.path == path]


def _path(url: str) -> str:
    return url.removeprefix(BASE_URL)


def _keeper(**replies: Reply) -> tuple[FakeHttp, HttpKeeper]:
    http = FakeHttp(replies=dict(replies.items()))
    return http, HttpKeeper(http=http, base_url=BASE_URL, token=TOKEN)


def _listing(*rows: Mapping[str, Any]) -> Reply:
    return Reply(200, {"items": list(rows), "next_cursor": None})


def _dispatch(procedure_id: str = PROCEDURE_ID) -> dict[str, Any]:
    """One row as `GET /executions` returns it, trimmed to what is read."""
    return {
        "execution_id": EXECUTION_ID,
        "procedure_id": procedure_id,
        "procedure_name": "tomography",
        "beamline": "2-bm",
        "step_count": 2,
        "reported_count": 0,
        "status": "Dispatched",
        "created_at": "2026-09-24T10:00:00Z",
        "updated_at": "2026-09-24T10:00:00Z",
    }


def _move(record: str = "2bmb:m1", to: float = 0.0) -> dict[str, Any]:
    return {"kind": "move", "step_id": MOVE_STEP_ID, "record": record, "to": to}


def _acquire(*scopes: str, plan_id: str = PLAN_ID) -> dict[str, Any]:
    return {
        "kind": "acquire",
        "step_id": ACQUIRE_STEP_ID,
        "plan_id": plan_id,
        "parameters": {"exposure": 0.1},
        "scopes": list(scopes) or ["2bmb:cam1:"],
    }


def _procedure(*steps: Mapping[str, Any], name: str = "tomography") -> Reply:
    return Reply(
        200, {"procedure_id": PROCEDURE_ID, "name": name, "beamline": "2-bm", "steps": list(steps)}
    )


def _plan(name: str = "tomo_scan") -> Reply:
    return Reply(200, {"plan_id": PLAN_ID, "name": name, "parameters_schema": {}})


def test_the_adapter_is_the_seam_the_core_asks_for() -> None:
    """The annotation is the check, and the assertion is the cheaper half.

    Nothing else in this tree ever assigns an `HttpKeeper` to an `Keeper`,
    because the entrypoint that will is not written yet, and a Protocol
    nothing is assigned to is a Protocol nothing is checked against. The
    annotation below makes the type checker compare the four signatures.
    The `isinstance` adds only that the names are present, which is what
    survives if somebody ever runs the tests without pyright.
    """
    _, adapter = _keeper()

    seam: Keeper = adapter

    assert isinstance(seam, Keeper)


def test_a_beamline_with_nothing_waiting_is_told_so_in_one_request() -> None:
    """An idle beamline is the common case and has to be the cheap one."""
    http, keeper = _keeper(**{"/executions": _listing()})

    assert keeper.take("2-bm", wait=30.0) is None
    assert [request.path for request in http.sent] == ["/executions"]


def test_the_intake_asks_only_for_dispatched_work_at_its_own_beamline() -> None:
    """A claim is a write with nothing to undo it.

    A conductor that asked without the filters and sorted afterwards
    could claim an execution belonging to another beamline, which is
    hardware it does not own, and the mistake would be one round trip
    too late to take back.
    """
    http, keeper = _keeper(**{"/executions": _listing()})

    keeper.take("7-bm", wait=5.0)

    params = http.sent[0].params
    assert params is not None
    assert params["beamline"] == "7-bm"
    assert params["status"] == "Dispatched"
    assert params["limit"] == "1"


def test_a_long_poll_gives_the_socket_longer_than_the_wait_it_asked_for() -> None:
    """The quiet failure this adapter would otherwise ship with.

    A client whose timeout is shorter than the wait raises on every idle
    poll, so a conductor only ever sees work that landed in the first few
    seconds. Nothing about the process or the route looks wrong while
    that is happening, which is why the margin is asserted here rather
    than left to whoever builds the client.
    """
    http, keeper = _keeper(**{"/executions": _listing()})

    keeper.take("2-bm", wait=30.0)

    asked = http.sent[0]
    assert asked.params is not None
    assert asked.params["wait"] == "30.0"
    assert asked.timeout is not None
    assert asked.timeout > 30.0


def test_a_refused_listing_is_raised_rather_than_read_as_an_idle_beamline() -> None:
    """A 403 and an empty page must not look the same to the loop.

    A conductor whose token was never granted the read would otherwise
    sit forever reporting nothing to do, at a beamline where work is
    piling up.
    """
    _, keeper = _keeper(**{"/executions": Reply(403, text="not granted execution:read")})

    with pytest.raises(RequestRefusedError) as refusal:
        keeper.take("2-bm", wait=0.0)

    assert refusal.value.status == 403


def test_an_assignment_carries_the_procedure_as_this_package_composes_one() -> None:
    """The translation, which is the whole of what `take` does after the fetch."""
    _, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(_move(), _acquire("2bmb:cam1:", "2bmb:m1")),
            f"/plans/{PLAN_ID}": _plan("tomo_scan"),
        }
    )

    assignment = keeper.take("2-bm", wait=0.0)

    assert assignment is not None
    assert assignment.execution_id == EXECUTION_ID
    assert assignment.procedure.name == "tomography"
    assert list(assignment.procedure.steps) == [
        Move(record="2bmb:m1", to=0.0),
        Acquire(
            plan="tomo_scan",
            claim=Claim.over("2bmb:cam1:", "2bmb:m1"),
            parameters={"exposure": 0.1},
        ),
    ]


def test_the_step_ids_line_up_with_the_steps_they_name() -> None:
    """Positional, which is what `Assignment` promises and what the walk relies on.

    An acquisition carries its step id into the engine's metadata, so a
    pairing off by one would file every run against the wrong step of the
    right execution, which reads as a plausible record rather than as an
    error.
    """
    _, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(_move(), _acquire()),
            f"/plans/{PLAN_ID}": _plan(),
        }
    )

    assignment = keeper.take("2-bm", wait=0.0)

    assert assignment is not None
    assert list(assignment.step_ids) == [MOVE_STEP_ID, ACQUIRE_STEP_ID]
    assert len(assignment.step_ids) == len(assignment.procedure.steps)


def test_a_plan_is_looked_up_once_however_many_procedures_cite_it() -> None:
    """Nothing renames a plan, so the second lookup could only repeat the first.

    A beamline running one routine all day would otherwise spend a
    request per acquisition asking AROC to confirm a name that cannot
    change.
    """
    http, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(_acquire(), _acquire()),
            f"/plans/{PLAN_ID}": _plan(),
        }
    )

    keeper.take("2-bm", wait=0.0)
    keeper.take("2-bm", wait=0.0)

    assert len(http.asked(f"/plans/{PLAN_ID}")) == 1


def test_a_scope_this_package_cannot_parse_refuses_the_whole_assignment() -> None:
    """AROC stores a scope as written and says so.

    The grammar belongs to whatever drives the procedure, so the two
    systems can disagree about one, and a step whose claim could not be
    built would run holding less than it touches. That is the undeclared
    scan this package exists to refuse, so the assignment goes rather
    than the claim.
    """
    _, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(_acquire(".")),
            f"/plans/{PLAN_ID}": _plan(),
        }
    )

    with pytest.raises(UnwalkableAssignmentError) as problem:
        keeper.take("2-bm", wait=0.0)

    assert problem.value.execution_id == EXECUTION_ID


def test_a_step_kind_this_conductor_does_not_know_refuses_the_assignment() -> None:
    """AROC may grow a third kind before this package can drive one.

    Guessing from the fields present would turn that into a procedure
    walked wrong, where refusing it is a procedure nobody drove.
    """
    _, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(
                {"kind": "transfer", "step_id": MOVE_STEP_ID}
            ),
        }
    )

    with pytest.raises(UnwalkableAssignmentError):
        keeper.take("2-bm", wait=0.0)


def test_a_claim_that_was_accepted_says_the_execution_is_this_conductors() -> None:
    _, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/claim": Reply(204)})

    assert keeper.claim(EXECUTION_ID) is True


def test_a_claim_another_conductor_won_is_not_an_error() -> None:
    """Nothing reserves a dispatch for whoever read it.

    Two conductors at one beamline seeing one execution is the expected
    case rather than a fault, and exactly one of them gets it. An
    adapter that raised here would make the ordinary outcome of that race
    look like a failure to the loop.
    """
    _, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/claim": Reply(409, text="not Dispatched")})

    assert keeper.claim(EXECUTION_ID) is False


def test_a_claim_refused_for_any_other_reason_is_raised() -> None:
    """A 404 means the two disagree about what was dispatched, which is not a race."""
    _, keeper = _keeper(
        **{f"/executions/{EXECUTION_ID}/claim": Reply(404, text="no such execution")}
    )

    with pytest.raises(RequestRefusedError) as refusal:
        keeper.claim(EXECUTION_ID)

    assert refusal.value.status == 404


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (
            Done(step="move 2bmb:m1 to 0.0"),
            {"index": 2, "outcome": "Done", "engine_reference": None},
        ),
        (
            Done(
                step="acquire tomo_scan",
                acquired=Acquired(
                    cites=Citation(execution_id=EXECUTION_ID, step_id=ACQUIRE_STEP_ID),
                    engine_reference="uid-9",
                    said="success",
                ),
            ),
            {"index": 2, "outcome": "Done", "engine_reference": "uid-9"},
        ),
        (
            Refused(
                step="acquire", holder="tomography[0]", overlap=frozenset({Scope.record("2bmb:m1")})
            ),
            {"index": 2, "outcome": "Refused"},
        ),
        (
            Broke(step="move", cause="TimeoutError: 2bmb:m1 did not get there"),
            {"index": 2, "outcome": "Broken", "cause": "TimeoutError: 2bmb:m1 did not get there"},
        ),
        (Skipped(step="acquire"), {"index": 2, "outcome": "Skipped"}),
    ],
    ids=["done", "done-carrying-a-run", "refused", "broke", "skipped"],
)
def test_a_step_report_carries_the_detail_its_outcome_allows(
    outcome: Outcome, expected: dict[str, Any]
) -> None:
    """AROC checks the detail against the outcome and refuses a stray field.

    A cause on anything but a break, or a reference on anything but a
    completion, comes back 400. So which fields travel is not a
    formatting choice here, it is the difference between a report that
    lands and one that does not.
    """
    http, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/steps": Reply(204)})

    keeper.report(EXECUTION_ID, 2, outcome)

    assert http.sent[0].json == expected


def test_a_refusal_reaches_aroc_as_a_refusal_and_not_as_its_reason() -> None:
    """The one thing this adapter knows and cannot pass on.

    AROC's step report allows no detail on a refusal, so the step that
    held the overlapping claim and the scopes that collided stay in this
    process. Sending either as a cause would be refused outright, and
    widening what a refusal may carry is a change to AROC's command.
    """
    http, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/steps": Reply(204)})

    keeper.report(
        EXECUTION_ID,
        0,
        Refused(
            step="acquire", holder="tomography[1]", overlap=frozenset({Scope.record("2bmb:m1")})
        ),
    )

    body = http.sent[0].json
    assert body is not None
    assert "tomography[1]" not in str(body)


def test_finishing_says_nothing_further_is_coming() -> None:
    http, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/end": Reply(204)})

    keeper.finish(EXECUTION_ID)

    assert [(request.method, request.path) for request in http.sent] == [
        ("POST", f"/executions/{EXECUTION_ID}/end")
    ]


def test_an_execution_something_else_already_ended_is_raised_rather_than_swallowed() -> None:
    """Where a 409 on a claim is a race, a 409 here is not one.

    A conductor going to end the execution it has been walking finds it
    already closed only if something else closed it, and that is worth
    hearing about rather than treating as the ordinary outcome the way a
    lost claim is.
    """
    _, keeper = _keeper(**{f"/executions/{EXECUTION_ID}/end": Reply(409, text="already ended")})

    with pytest.raises(RequestRefusedError) as refusal:
        keeper.finish(EXECUTION_ID)

    assert refusal.value.status == 409


def test_every_request_carries_the_token_it_was_configured_with() -> None:
    """Including the reads. AROC grants a command per verb, not a session."""
    http, keeper = _keeper(
        **{
            "/executions": _listing(_dispatch()),
            f"/procedures/{PROCEDURE_ID}": _procedure(_move()),
            f"/executions/{EXECUTION_ID}/claim": Reply(204),
            f"/executions/{EXECUTION_ID}/end": Reply(204),
        }
    )

    keeper.take("2-bm", wait=0.0)
    keeper.claim(EXECUTION_ID)
    keeper.finish(EXECUTION_ID)

    assert http.sent
    for request in http.sent:
        assert request.headers is not None
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
