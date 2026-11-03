"""A turning seam over the keeper's HTTP API, which is the only way in.

The same surface `http_tasking` uses and the same argument for it: a
driver dials out and nothing dials back. What differs is which verbs it
needs, and that it needs no claim at all. Two drivers turning one pursuit
are serialized by the record, which refuses the second round about an
execution the first already asked about, so nothing here coordinates.

## Six routes

    pursuits      GET  /pursuits?status=Running
                  GET  /pursuits/{pursuit_id}
    ended         GET  /executions?beamline=&status=Ended
    answered      GET  /inquiries/{inquiry_id}
    open_round    POST /pursuits/{pursuit_id}/rounds
    close_round   POST /pursuits/{pursuit_id}/rounds/{index}/close

`pursuits` is two requests because the listing is a summary: it carries a
round count and not the rounds, and a count cannot tell a question still
outstanding from one already answered. The detail read is where the rounds
are, so each running pursuit costs one more request. That is affordable
because pursuits are few and long-lived, which is the opposite of how
executions behave, and it is why the listing is right to leave them out.

## Why an answered inquiry is one with a conclusion

Not one with a particular status. The conclusion is the thing a round is
closed on, it is null until a thinker reaches one, and the record's own
read puts it beside the status for exactly this reason. Asking about the
field that is used keeps this from disagreeing with the handler that acts
on it.

## Why the client shape is written out again

`http_tasking` declares a Response and an HttpClient that read almost the
same as the two below. They are not shared, because an adapter that
imported a sibling would join two outside systems through this package
and drag the other one's library behind it. The duplication is the rule
working rather than an oversight.

## What a refused open means here

The record refuses a second round about one execution with a conflict, and
this returns nothing rather than raising. A driver that crashed between
opening a round and hearing about it comes back, tries the same execution
and is told no, which is the retry guard doing its job. Every other
refusal raises, because none of them is a race this driver lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from conductor.turning import Closed, Pursuit, Round

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@runtime_checkable
class Response(Protocol):
    """The part of an HTTP response this adapter reads."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


@runtime_checkable
class HttpClient(Protocol):
    """The two verbs this adapter uses, shaped the way clients shape them."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | Sequence[str]] | None = ...,
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


class TurningRefusedError(RuntimeError):
    """The keeper answered a pursuit call, and the answer was no.

    Written here rather than shared with the tasking adapter, which has
    one that reads almost the same. Two adapters that shared code would
    be two outside systems joined through this package, and the rule
    against it is worth more than the lines it costs: what looks like one
    HTTP client today is two contacts with two surfaces, and either may
    move without the other.

    A transport failure is not this. It comes out of the HTTP client
    unchanged, because a request that never arrived and one that was
    turned down want opposite handling.
    """

    def __init__(self, status: int, detail: str, *, method: str, path: str) -> None:
        super().__init__(f"{method} {path}: {status} {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path


RUNNING: Final = "Running"
ENDED: Final = "Ended"

PAGE: Final = "200"
"""How many rows a listing is asked for.

One page and no cursor. A facility with more running pursuits than this
has a different problem from the one this driver solves, and a loop that
paged would hold a cursor across passes, which is the state this whole
design is arranged not to keep.
"""


@dataclass(frozen=True, slots=True)
class HttpTurning:
    """Reads pursuits from a running keeper and moves them on.

    `base_url` and `token` rather than a configuration object, for the
    reason `HttpTasking` gives: it needs two strings, and a test building
    a whole configuration to supply them would be building it for nothing.
    """

    http: HttpClient
    base_url: str
    token: str

    def pursuits(self) -> Sequence[Pursuit]:
        """Every pursuit still authorized to advance, with its rounds."""
        page = self._get("/pursuits", params={"status": RUNNING, "limit": PAGE})
        return [self._pursuit(str(row["pursuit_id"])) for row in page.get("items", [])]

    def ended(self, beamline: str) -> Sequence[str]:
        """Executions at one beamline that have finished, oldest first.

        The listing answers newest first, the way every listing here does,
        and this reverses it. A pursuit observes what happened in the
        order it happened, and a driver handed the newest first would
        advance on the latest scan and never reach the one before it.
        """
        page = self._get(
            "/executions",
            params={"beamline": beamline, "status": ENDED, "limit": PAGE},
        )
        rows = page.get("items", [])
        return [str(row["execution_id"]) for row in reversed(rows)]

    def answered(self, inquiry_id: str) -> bool:
        """Whether a thinker has concluded on this inquiry yet."""
        inquiry = self._get(f"/inquiries/{inquiry_id}", params={})
        return inquiry.get("conclusion") is not None

    def open_round(self, pursuit_id: str, execution_id: str) -> str | None:
        """Ask about one execution, and say which inquiry carries the question."""
        path = f"/pursuits/{pursuit_id}/rounds"
        response = self.http.post(
            self._url(path),
            headers=self._headers(),
            json={"execution_id": execution_id},
        )
        if response.status_code == 409:
            return None
        if response.status_code >= 400:
            raise TurningRefusedError(response.status_code, response.text, method="POST", path=path)
        return str(response.json()["inquiry_id"])

    def close_round(self, pursuit_id: str, index: int) -> Closed:
        """Read the answer, act on it, and end the round."""
        path = f"/pursuits/{pursuit_id}/rounds/{index}/close"
        response = self.http.post(self._url(path), headers=self._headers(), json=None)
        if response.status_code >= 400:
            raise TurningRefusedError(response.status_code, response.text, method="POST", path=path)
        body = response.json()
        dispatched = body.get("dispatched_id")
        return Closed(
            outcome=str(body["outcome"]),
            dispatched_id=None if dispatched is None else str(dispatched),
        )

    def _pursuit(self, pursuit_id: str) -> Pursuit:
        detail = self._get(f"/pursuits/{pursuit_id}", params={})
        return Pursuit(
            pursuit_id=pursuit_id,
            beamline=str(detail["beamline"]),
            rounds=tuple(
                Round(
                    index=int(turn["index"]),
                    execution_id=str(turn["execution_id"]),
                    inquiry_id=str(turn["inquiry_id"]),
                    outcome=None if turn.get("outcome") is None else str(turn["outcome"]),
                )
                for turn in detail.get("rounds", [])
            ),
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.http.get(self._url(path), headers=self._headers(), params=params)
        if response.status_code >= 400:
            raise TurningRefusedError(response.status_code, response.text, method="GET", path=path)
        body: dict[str, Any] = response.json()
        return body

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


__all__ = ["HttpClient", "HttpTurning", "Response", "TurningRefusedError"]
