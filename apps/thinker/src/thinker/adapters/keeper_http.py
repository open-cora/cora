"""The four keeper seams over its HTTP API, which is the only way in.

Every call here goes out. The keeper holds no registry of thinkers and
dials nothing, so what this reads and what it writes leave through the same
surface every other client uses.

## Seven verbs over eight routes

    take      GET  /inquiries?status=Open&limit=1&wait=
    read      GET  /executions/{execution_id}
              GET  /procedures/{procedure_id}
    ask       POST /inquiries
    question  GET  /inquiries/{inquiry_id}
    claim     POST /inquiries/{inquiry_id}/claim
    answer    POST /inquiries/{inquiry_id}/answer
    propose   POST /proposals

`take` and `question` answer the same three facts off the same record,
and both are here because they are asked at different moments. One names
the question it wants and the other is asking which question to name.

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

A 400 is the keeper saying the values do not satisfy the schema the
operation declares. It travels as an error rather than becoming a quieter
conclusion, because a proposal that could not have run is worth more as a
failure than as a row: something concluded a run that was never possible,
and turning that into an abstention would file the evidence away.

## Why a refused claim is the one status that is not an error

`claim` answers 409 when another thinker holds the question or when one
has already been answered. That is not a fault and it does not travel as
one: it comes back as False, and the caller stops without thinking. Every
other unexpected status here raises, because every other one means the
keeper and this adapter disagree about something.

## Where the four conclusions become four words

`CONCLUSIONS` below, and nowhere else. Public, like `ENDED` beside it, so
the test that checks it covers every conclusion class can read it: a private
mapping would be one the exhaustiveness check could not reach, which would
leave the four-to-four correspondence resting on somebody noticing. The
record's vocabulary and this package's class names are the same four words
today, so the mapping looks like it could be `type(conclusion).__name__`.
Writing it out is what stops a rename on this side quietly changing what
lands in a table nobody can edit afterwards, and `test_keeper_http.py`
checks that every conclusion class has an entry rather than trusting the
four to stay four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from thinker.case import Question, Reading
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from thinker.case import Boundary


CONCLUSIONS: Final[dict[type[Conclusion], str]] = {
    Propose: "Propose",
    Stop: "Stop",
    Abstain: "Abstain",
    Refer: "Refer",
}
"""Each conclusion, and the word the record spells it with.

Written out rather than derived from the class name. The two sides agree
today and there is no shared package to make them agree tomorrow, so the
mapping is the seam between two vocabularies rather than a coincidence
being relied on.
"""

_ALREADY_TAKEN: Final = 409
"""The one status a claim may answer without this being an error."""


OPEN: Final = "Open"
"""The one inquiry status a thinker goes looking for.

A question nothing has taken up. One in any other status either has a
thinker on it or has been answered, and asking for those would be asking
to spend an inference on work that is done or being done.
"""

TIMEOUT_MARGIN_SECONDS: Final = 10.0
"""How much longer than its wait a held request gives the socket.

Covers the round trip and the keeper's own work either side of the wait.
Generous rather than tight: a margin that is too small turns every quiet
wait into a timeout, and one that is too large costs nothing, because the
keeper answers at the ceiling and the client never reaches this.

Without it this adapter would inherit the client-wide timeout, which the
entrypoint sets to the same thirty seconds a wait asks for. That failure
is quiet in the worst way: the process is alive, the route is right, and
every wait that nothing answers raises instead of returning empty.
"""


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
    """Something went wrong between this thinker and the keeper."""


class UnknownConclusionError(KeeperError):
    """A conclusion class this adapter has no word for.

    Unreachable while the four classes and the four words stay in step,
    and here so that adding a fifth conclusion fails at the write rather
    than sending the record something it will refuse or, worse, a word it
    happens to accept.
    """

    def __init__(self, conclusion: type) -> None:
        super().__init__(
            f"{conclusion.__name__} has no word in this adapter, so there is nothing "
            "to write on an inquiry. Give it one in CONCLUSIONS."
        )
        self.conclusion = conclusion


class RequestRefusedError(KeeperError):
    """The keeper answered, and the answer was no.

    Carries the status, because the statuses mean different things and only
    the caller can decide what to do about one:

        400  the parameters do not satisfy the operation's schema. whatever
             concluded this proposed a run that could not have happened.
        401  no credential was accepted. configuration.
        403  this thinker is registered and is not granted that command.
             also configuration.
        404  nothing has that id, which means this thinker was pointed at
             an execution, a procedure or an operation the keeper does not hold.

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

    def take(self, wait: float) -> Question | None:
        """Ask for one open question, holding the request open for a while.

        One row rather than a page. A thinker answers one question at a
        time, and asking for more would mean holding rows another thinker
        may claim while the first is still thinking.

        Everything a `Question` holds is on the row, so this is one
        request and not two. The listing carries the objective where the
        proposal listing leaves its parameters off, which the keeper
        decided partly so that a caller scanning for the question it
        cares about can read one.

        The timeout is passed per request rather than left to the client.
        A client built with a shorter one raises on every wait that
        nothing answers, and a thinker would then only ever see questions
        that landed inside the first few seconds of each ask.
        """
        page = self._get(
            "/inquiries",
            params={"status": OPEN, "limit": "1", "wait": str(wait)},
            timeout=wait + TIMEOUT_MARGIN_SECONDS,
        )
        rows: Sequence[Mapping[str, Any]] = page["items"]
        if not rows:
            return None

        row = rows[0]
        return Question(
            inquiry_id=str(row["inquiry_id"]),
            execution_id=str(row["execution_id"]),
            objective=str(row["objective"]),
        )

    def ask(self, execution_id: str, objective: str) -> Question:
        """Open an inquiry, and hand it back with the id the keeper minted.

        No time is sent. The keeper is the authority for when a question
        was put, because the call is the putting, and a field here would
        be a second opinion about a moment this system was present for.

        A 400 is the objective falling outside the bound the record
        declares, and a 404 is an execution nothing has dispatched. Both
        travel as errors: neither is a thinking that reached a conclusion.
        """
        path = "/inquiries"
        response = self.http.post(
            self._url(path),
            json={"execution_id": execution_id, "objective": objective},
            headers=self._headers(),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return Question(
            inquiry_id=str(response.json()["inquiry_id"]),
            execution_id=execution_id,
            objective=objective,
        )

    def question(self, inquiry_id: str) -> Question:
        """Read back a question somebody else put.

        Three fields are taken off a record that carries more. What is
        left behind is the status, the conclusion and the observation
        boundary, which are either about an answer that has not happened
        or about one this thinker is not the reader of.
        """
        inquiry = self._get(f"/inquiries/{inquiry_id}")
        return Question(
            inquiry_id=str(inquiry["inquiry_id"]),
            execution_id=str(inquiry["execution_id"]),
            objective=str(inquiry["objective"]),
        )

    def claim(self, inquiry_id: str) -> bool:
        """Take the question up, and say whether it was this thinker's to take.

        409 is the ordinary refusal and comes back as False: another
        thinker holds it, or one has already answered it. The keeper does
        not distinguish those two on the status and neither does this,
        because the caller does the same thing either way.

        204 is the success, and anything else raises. A 404 in particular
        is not a refusal to claim, it is an id naming no inquiry at all,
        and reporting that as "somebody else has it" would send a caller
        looking for a thinker that does not exist.
        """
        path = f"/inquiries/{inquiry_id}/claim"
        response = self.http.post(self._url(path), json={}, headers=self._headers())
        if response.status_code == _ALREADY_TAKEN:
            return False
        if response.status_code != 204:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return True

    def answer(
        self,
        inquiry_id: str,
        conclusion: Conclusion,
        boundary: Boundary,
        proposal_id: str | None,
    ) -> None:
        """Write the conclusion and the boundary onto the inquiry.

        The conclusion becomes one of four words through `CONCLUSIONS`,
        which raises on a class it does not know rather than falling back
        to the class name. A fifth conclusion added on this side has to be
        given a word deliberately, because the record will refuse one it
        has no meaning for and the useful moment to find that out is here.

        `proposal_id` is sent as null for the three arms that have none.
        The keeper refuses the combinations that cannot be true, so this
        sends what happened and lets the record be the one that checks.
        """
        word = CONCLUSIONS.get(type(conclusion))
        if word is None:
            raise UnknownConclusionError(type(conclusion))

        path = f"/inquiries/{inquiry_id}/answer"
        response = self.http.post(
            self._url(path),
            json={
                "conclusion": word,
                "observed_step_count": boundary.observed_step_count,
                "execution_ended": boundary.execution_ended,
                "proposal_id": proposal_id,
            },
            headers=self._headers(),
        )
        if response.status_code != 204:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)

    def propose(self, operation_id: str, parameters: Mapping[str, object]) -> str:
        """Put a run forward, and return the id of the proposal that records it.

        No idempotency key. The route takes one, and a thinker has nothing
        to put in it: two thinkings over one execution are two acts of
        advising rather than one retried, and collapsing them would hide
        a thinker that had thought twice. A loop does not change that,
        because it retries a turn that wrote nothing rather than an act
        half done.
        """
        path = "/proposals"
        response = self.http.post(
            self._url(path),
            json={"operation_id": operation_id, "parameters": dict(parameters)},
            headers=self._headers(),
        )
        if response.status_code != 201:
            raise RequestRefusedError(response.status_code, response.text, method="POST", path=path)
        return str(response.json()["proposal_id"])

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        response = self.http.get(
            self._url(path),
            params=params,
            headers=self._headers(),
            timeout=timeout,
        )
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
