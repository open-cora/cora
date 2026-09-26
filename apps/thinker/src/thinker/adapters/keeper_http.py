"""The `Keeper` seam over the keeper's HTTP API, which is the only way in.

Every call here goes out. The keeper holds no registry of thinkers and
dials nothing, so what this reads and what it writes leave through the same
surface every other client uses.

## Two verbs over three routes

    read      GET  /executions/{execution_id}
              GET  /procedures/{procedure_id}
    propose   POST /proposals

Reading is two requests because a case is two halves and the keeper keeps
them apart. The execution says how each of its steps ended and cites the
composed step it was dispatched from; what that step was asked to do is the
procedure's to say. The keeper's own reading route says as much, and says
not to recover it by taking a step's description apart.

## The join is by id, and the keeper names the key

An execution step carries `procedure_step_id`, and a procedure step carries
`step_id`. Those are the same value under the two vocabularies that own it,
and pairing them is the whole of the assembly below. Position would look
like it worked: both lists come back in the procedure's order today. It
would be a guess that happened to hold, and the day a step is added it
would pair every later step with the wrong outcome and say nothing.

## Passed through rather than interpreted

A procedure step reaches the case as the mapping the keeper sent, and an
outcome reaches it as the keeper's own word. Both could be rewritten into
shapes of this package's own, and neither is: a thinker that normalised
them would be deciding what about a step matters before anything has read
it, and the discarded half would be invisible from the other side of the
seam.

The one reading that is not a pass-through is `ended`, which is the status
compared against the single value the keeper calls terminal.

## What a refusal on a proposal means

A 400 is the keeper saying the values do not satisfy the schema the plan
declares. It travels as an error rather than becoming a quieter conclusion,
because a proposal that could not have run is worth more as a failure than
as a row: something concluded a run that was never possible, and turning
that into an abstention would file the evidence away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from thinker.case import Reading

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


ENDED: Final = "Ended"
"""The one execution status the keeper calls terminal.

Compared against rather than counted towards. An execution with an outcome
against every step has not necessarily been closed, and one closed early
has outcomes against only some, so neither question answers the other.
"""


@runtime_checkable
class Response(Protocol):
    """The part of an HTTP response this adapter reads.

    Narrower than any real client's, so a test can supply one and so that
    changing the HTTP library is a change at the entrypoint rather than
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
    of a dependency. `apps/conductor` does the same at its own keeper
    adapter: what is specific here is the shape of a call, not a package.
    """

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = ...,
    ) -> Response: ...

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = ...,
        headers: Mapping[str, str] | None = ...,
    ) -> Response: ...


class KeeperError(RuntimeError):
    """Something went wrong between this thinker and the keeper."""


class RequestRefusedError(KeeperError):
    """The keeper answered, and the answer was no.

    Carries the status, because the statuses mean different things and only
    the caller can decide what to do about one:

        400  the parameters do not satisfy the plan's schema. whatever
             concluded this proposed a run that could not have happened.
        401  no credential was accepted. configuration.
        403  this thinker is registered and is not granted that command.
             also configuration.
        404  nothing has that id, which means this thinker was pointed at
             an execution, a procedure or a plan the keeper does not hold.

    A transport failure is not this. It leaves the HTTP client unchanged,
    because a request that never arrived and a request that was turned down
    want opposite handling.
    """

    def __init__(self, status: int, detail: str, *, method: str, path: str) -> None:
        super().__init__(f"{method} {path}: {status} {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path


@dataclass(slots=True)
class HttpKeeper:
    """Reads an execution against its procedure, and puts a run forward.

    `base_url` and `token` rather than a configuration object, so this
    module stays reachable without one: it needs two strings, and a test
    building a whole configuration to supply them would be building it for
    nothing.

    The token is what this thinker advises as. Nothing in a proposal says
    who is proposing, because the keeper reads that off the authenticated
    principal, so a thinker is an actor exactly the way a person is.
    """

    http: HttpClient
    base_url: str
    token: str

    def read(self, execution_id: str) -> Reading:
        """Read one execution, and the procedure it was dispatched from.

        The execution is fetched first and names the procedure, so a bad id
        costs one request and the second is never made against a procedure
        nothing cites.

        The name comes off the procedure rather than off the execution,
        which also carries one. They agree today. Reading it here means
        that a case cannot end up naming one procedure and listing the
        steps of another.

        Nothing is paired here. The two halves go back as they were read,
        keyed the way the keeper keys them, and the core joins them.
        """
        execution = self._get(f"/executions/{execution_id}")
        procedure = self._get(f"/procedures/{execution['procedure_id']}")

        composed: Sequence[Mapping[str, Any]] = procedure["steps"]
        walked: Sequence[Mapping[str, Any]] = execution["steps"]

        return Reading(
            execution_id=str(execution["execution_id"]),
            procedure=str(procedure["name"]),
            asked=tuple((str(step["step_id"]), dict(step)) for step in composed),
            became={str(step["procedure_step_id"]): _outcome(step["outcome"]) for step in walked},
            ended=str(execution["status"]) == ENDED,
        )

    def propose(self, plan_id: str, parameters: Mapping[str, object]) -> str:
        """Put a run forward, and return the id of the proposal that records it.

        No idempotency key. The route takes one, and a thinker has nothing
        to put in it: two runs of a thinker over one execution are two acts
        of advising rather than one retried, and collapsing them would hide
        a thinker that had been invoked twice.
        """
        path = "/proposals"
        response = self.http.post(
            self._url(path),
            json={"plan_id": plan_id, "parameters": dict(parameters)},
            headers=self._headers(),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return str(response.json()["proposal_id"])

    def _get(self, path: str) -> Any:
        response = self.http.get(self._url(path), headers=self._headers())
        if response.status_code != 200:
            raise RequestRefusedError(response.status_code, response.text, method="GET", path=path)
        return response.json()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _outcome(raw: object) -> str | None:
    """The keeper's word for how a step ended, or nothing if it said none.

    Null here is the keeper's way of saying a step has reported nothing,
    which it distinguishes from a step that was skipped. Both reach a case
    intact: the first as `None` and the second as the word `Skipped`, and
    flattening either into the other would lose the difference between a
    step the walk never arrived at and one it arrived at and passed over.
    """
    return None if raw is None else str(raw)


__all__ = [
    "ENDED",
    "HttpClient",
    "HttpKeeper",
    "KeeperError",
    "RequestRefusedError",
    "Response",
]
