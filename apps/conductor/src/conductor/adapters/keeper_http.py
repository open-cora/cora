"""The `Keeper` seam over the keeper's HTTP API, which is the only way in.

The keeper holds no registry of conductors and dials nothing. Everything this
conductor learns and everything it reports leaves through the surface any
other client uses, which is what `seams.Keeper` means by every call going
out and none coming in.

## Four verbs over five routes

    take     GET  /executions?beamline=&status=Dispatched&wait=
             GET  /procedures/{procedure_id}
             GET  /plans/{plan_id}
    claim    POST /executions/{execution_id}/claim
    report   POST /executions/{execution_id}/steps
    finish   POST /executions/{execution_id}/end

`take` is more than one request because the listing is a summary. It says
an execution was dispatched and which routine it cites, and a walk needs
the routine. The steps are deliberately not on those rows: a page of them
carrying every step of every execution would be almost entirely steps.

## Why a plan is looked up by id, and why the answer is kept

An acquisition step cites a `plan_id`. This package's `Acquire` holds a
`plan`, which is the name the engine knows the routine by. Those are one
routine under the two vocabularies that own it, and only the keeper can say
which name goes with which id.

The answers are kept for the life of the adapter, because nothing renames
a plan: the stream carries one event for one and there is no second that
could change a name. A conductor walking a hundred procedures over one
plan asks once.

## The client is given, and the timeout is not

An HTTP client is passed in, the way `apps/reporter` passes one. The
connection pool, TLS and retries belong where a deployment sets them, and
a test can supply a transport that asserts on a request rather than
sending it.

`take` passes its own timeout, which is the exception and the reason the
shape below has one. A long poll asks the server to hold the request for
`wait` seconds, so a client built with a shorter timeout raises on every
idle poll, and a conductor would then only ever see work that landed
inside the first few. That failure is quiet in the worst way: the process
is alive, the route is correct, and dispatches are picked up late or not
at all.

## What the keeper is not told, and why

**A refusal's reason.** `Refused` here names the step holding the
overlapping claim and the scopes that collided. The keeper's step report allows
no detail on that outcome, so it records that a step was refused and
nothing about what it ran into. The collision stays in this process's own
tally and its log. Widening that is a change to the keeper's report command
rather than something an adapter may decide by putting the reason in a
field meant for something else.

**A moment.** No outcome here carries a time, so the keeper stamps each report
as it arrives. That is accurate to within one request, because a report
goes out as its step ends.

## `Broke` travels as `Broken`

The one word that differs across the two vocabularies. This package names
an outcome for what happened to the step, and the keeper names it for the state
the step ended in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from conductor.claims import Claim, InvalidScopeError
from conductor.outcomes import Broke, Done, Refused, Skipped
from conductor.procedure import Acquire, InvalidProcedureError, Move, Procedure
from conductor.seams import Assignment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.outcomes import Outcome
    from conductor.procedure import Step

DISPATCHED: Final = "Dispatched"
"""The one execution status a conductor asks for.

Work nothing has taken up. An execution in any other status either has a
driver or is over, and a conductor that asked for those would be asking
to drive hardware somebody else is already driving.
"""

TIMEOUT_MARGIN_SECONDS: Final = 10.0
"""How much longer than its wait a long poll gives the socket.

Covers the round trip and the server's own work either side of the wait.
Generous rather than tight: a margin that is too small turns every idle
poll into a timeout, and one that is too large costs nothing, because the
server answers at its ceiling and the client never reaches this.
"""


@runtime_checkable
class Response(Protocol):
    """The part of an HTTP response this adapter reads.

    Narrower than any real client's, so a test can supply one and so that
    swapping the HTTP library is a change at the entrypoint rather than
    here.
    """

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


@runtime_checkable
class HttpClient(Protocol):
    """The two verbs this adapter uses, shaped the way clients shape them.

    Written out rather than imported, which is what keeps this module free
    of a dependency. `bluesky_acquisition` does the same with the engine
    it drives, and for the same reason: what is specific here is the shape
    of a call, not a package.
    """

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = ...,
        headers: Mapping[str, str] | None = ...,
        timeout: float | None = ...,
    ) -> Response: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = ...,
        headers: Mapping[str, str] | None = ...,
    ) -> Response: ...


class KeeperError(RuntimeError):
    """Something went wrong between this conductor and the keeper."""


class RequestRefusedError(KeeperError):
    """The keeper answered, and the answer was no.

    Carries the status, because the statuses mean different things to the
    loop around this and only it can decide:

        401  no credential was accepted. configuration, and no amount of
             asking again will fix it.
        403  this conductor is not granted that command. also
             configuration.
        404  the execution is not there, which means the keeper and this
             conductor disagree about what was dispatched.
        409  the move is not one the record allows now. on a claim that
             is another conductor winning and is handled rather than
             raised; on a report or an ending it means something else
             moved the record.

    A transport failure is not this. It comes out of the HTTP client
    unchanged, because a request that never arrived and a request that
    was turned down want opposite handling: the first is worth trying
    again and the second is not.
    """

    def __init__(self, status: int, detail: str, *, method: str, path: str) -> None:
        super().__init__(f"{method} {path}: {status} {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path


class UnwalkableAssignmentError(KeeperError):
    """The keeper dispatched something this package cannot build a procedure from.

    Both systems check what they store, and they check nearly the same
    things: both refuse an empty procedure, an empty record name and an
    acquisition declaring no devices. What the keeper does not check is the
    scope grammar, which it stores as written and says so, because the
    grammar belongs to whatever drives the procedure. So a scope the keeper
    holds happily can be one `claims` will not parse.

    Raised rather than worked around. A procedure whose claims cannot be
    built is one whose steps would run holding less than they touch,
    which is the undeclared scan this package exists to refuse.
    """

    def __init__(self, execution_id: str, reason: str) -> None:
        super().__init__(
            f"the execution {execution_id} cites a procedure this conductor cannot walk: {reason}"
        )
        self.execution_id = execution_id
        self.reason = reason


@dataclass(slots=True)
class HttpKeeper:
    """Asks a running keeper for work, and tells it how the work went.

    `base_url` and `token` rather than a configuration object, so that
    this module stays reachable without one: it needs two strings, and a
    test building a whole configuration to supply them would be building
    it for nothing.
    """

    http: HttpClient
    base_url: str
    token: str
    _plan_names: dict[str, str] = field(default_factory=dict[str, str])

    def take(self, beamline: str, wait: float) -> Assignment | None:
        """Ask for one execution dispatched to this beamline and unclaimed.

        One row rather than a page. A conductor walks one procedure at a
        time, and asking for more would mean holding rows that a second
        conductor may claim while the first is still walking.

        The listing is answered before the routine is fetched, so a beamline
        with nothing waiting costs exactly one held request.
        """
        page = self._get(
            "/executions",
            params={
                "beamline": beamline,
                "status": DISPATCHED,
                "limit": "1",
                "wait": str(wait),
            },
            timeout=wait + TIMEOUT_MARGIN_SECONDS,
        )
        rows: Sequence[Mapping[str, Any]] = page["items"]
        if not rows:
            return None

        row = rows[0]
        execution_id = str(row["execution_id"])
        procedure = self._get(f"/procedures/{row['procedure_id']}")
        return self._assignment(execution_id, procedure)

    def claim(self, execution_id: str) -> bool:
        """Say this conductor is driving that execution.

        A 409 is the ordinary outcome of a race that had to happen
        somewhere, so it comes back as False rather than as a refusal.
        Nothing reserves a row for whoever read it, and two conductors
        seeing one dispatch is expected.

        No body. The only field the route takes is when it happened, and
        the moment a claim happens is the moment this request is made, so
        letting the keeper stamp its arrival says the same thing without a
        second clock in the picture.
        """
        path = f"/executions/{execution_id}/claim"
        response = self.http.post(self._url(path), headers=self._headers())
        if response.status_code == 204:
            return True
        if response.status_code == 409:
            return False
        raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)

    def report(self, execution_id: str, index: int, outcome: Outcome) -> None:
        """Say how the step at that index ended."""
        path = f"/executions/{execution_id}/steps"
        self._post(path, _step_report(index, outcome))

    def finish(self, execution_id: str) -> None:
        """Say nothing further is coming for that execution.

        A 409 raises here where it does not on a claim. An execution
        already ended when its own driver goes to end it is not a race
        this conductor lost, it is something else having closed a record
        this conductor was still walking, and that is worth hearing about.
        """
        self._post(f"/executions/{execution_id}/end", None)

    def _assignment(self, execution_id: str, procedure: Mapping[str, Any]) -> Assignment:
        """Turn the keeper's procedure into one this package can walk.

        Plan names are resolved first, before anything is built. That
        keeps a lookup that was refused distinguishable from a step that
        could not be built: the first is an `KeeperError` about reaching
        the keeper and the second is about what the keeper sent.
        """
        raw: Sequence[Mapping[str, Any]] = procedure["steps"]
        named = {
            str(step["plan_id"]): self._plan_name(str(step["plan_id"]))
            for step in raw
            if step["kind"] == "acquire"
        }

        try:
            walkable = Procedure(
                name=str(procedure["name"]),
                steps=tuple(_step(step, named) for step in raw),
            )
        except (InvalidProcedureError, InvalidScopeError) as problem:
            raise UnwalkableAssignmentError(execution_id, str(problem)) from problem

        return Assignment(
            execution_id=execution_id,
            procedure=walkable,
            step_ids=tuple(str(step["step_id"]) for step in raw),
        )

    def _plan_name(self, plan_id: str) -> str:
        """The name an engine knows a plan by, asked for once."""
        if plan_id not in self._plan_names:
            self._plan_names[plan_id] = str(self._get(f"/plans/{plan_id}")["name"])
        return self._plan_names[plan_id]

    def _get(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        response = self.http.get(
            self._url(path), params=params, headers=self._headers(), timeout=timeout
        )
        if response.status_code != 200:
            raise RequestRefusedError(response.status_code, response.text, method="GET", path=path)
        return response.json()

    def _post(self, path: str, body: Mapping[str, Any] | None) -> None:
        """Send a command and accept only the one answer that means it landed."""
        response = self.http.post(self._url(path), json=body, headers=self._headers())
        if response.status_code != 204:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _step(raw: Mapping[str, Any], named: Mapping[str, str]) -> Step:
    """Build one step, with the plan names already in hand.

    The kind discriminates, because it is what the keeper's own surface
    discriminates on, and a step whose kind this does not know is a step
    the keeper has grown and this has not. Guessing from the fields present
    would turn that into a procedure walked wrong rather than one refused.
    """
    match raw["kind"]:
        case "move":
            return Move(record=str(raw["record"]), to=float(raw["to"]))
        case "acquire":
            return Acquire(
                plan=named[str(raw["plan_id"])],
                claim=Claim.over(*(str(scope) for scope in raw["scopes"])),
                parameters=dict(raw["parameters"]),
            )
        case unknown:
            raise InvalidProcedureError(
                f"the step kind {unknown!r} is one the keeper composes and this "
                "conductor cannot drive"
            )


def _step_report(index: int, outcome: Outcome) -> dict[str, Any]:
    """One step's ending, in the fields the keeper's report command takes.

    Each outcome carries exactly the detail its own allows, which the
    domain checks on arrival: a cause on anything but a break, or a
    reference on anything but a completion, is refused over both of
    the keeper's surfaces rather than by a schema on one of them.
    """
    match outcome:
        case Done(acquired=acquired):
            return {
                "index": index,
                "outcome": "Done",
                "engine_reference": None if acquired is None else acquired.engine_reference,
            }
        case Refused():
            return {"index": index, "outcome": "Refused"}
        case Broke(cause=cause):
            return {"index": index, "outcome": "Broken", "cause": cause}
        case Skipped():
            return {"index": index, "outcome": "Skipped"}


__all__ = [
    "DISPATCHED",
    "TIMEOUT_MARGIN_SECONDS",
    "HttpClient",
    "HttpKeeper",
    "KeeperError",
    "RequestRefusedError",
    "Response",
    "UnwalkableAssignmentError",
]
