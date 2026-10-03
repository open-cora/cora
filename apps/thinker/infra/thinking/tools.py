"""What a profile may look up before it decides anything.

A case says what one execution was asked to do and what became of it. That
is enough for a table of rules and not enough for a judgement: it does not
say which parameters the operation would even accept, what has already been
tried at this beamline, or whether any of it produced data.

So these three read the record and hand back plain values. They are
gathered before the prompt is built rather than offered to the model as
callable tools, which keeps one round trip, keeps the result the same for
the same record, and depends on nothing the gateway may or may not support.

## Why this is here and not behind a seam

A thinker needs network access to the record and to whatever does the
thinking, and nothing else. It already holds a client for the first, and
this is the same client against the same record with the same credential.
Adding a seam would be adding one for a capability the thinker already has.

## Where the credential comes from

The same file the service already reads, at mode 600, through the loader
the service already uses. The profile factory is called with no arguments,
so something has to name that file, and an environment variable does: the
unit sets it to the path it is already passing on the command line. The
token itself is deliberately not in the environment, because a unit file in
a shared home is world readable and a token at mode 600 is not.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

import httpx

from thinker.config import load

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CONFIG_VARIABLE: Final = "CORA_THINKER_CONFIG"
"""Which file holds the keeper's address and this thinker's token."""

TIMEOUT: Final = 20.0
"""Long enough for a listing, short enough that a thinking does not hang.

Nothing here is a held request. The one call that waits is the intake's,
and that is the service's rather than a profile's.
"""


@runtime_checkable
class Reading(Protocol):
    """What a profile may ask of the record, named rather than imported.

    A Protocol so a profile is typed against the questions rather than
    against the class that answers them, which is the same reason
    `thinker.seams` holds Protocols: a suite can stand something else in
    without the profile knowing, and does.
    """

    def execution(self, execution_id: str) -> Mapping[str, Any]: ...

    def operation_schema(self, operation_id: str) -> Mapping[str, Any]: ...

    def prior_runs(self, beamline: str, limit: int = 10) -> Sequence[Mapping[str, Any]]: ...

    def datasets_for(self, step_id: str) -> Sequence[Mapping[str, Any]]: ...

    def procedure(self, procedure_id: str) -> Mapping[str, Any]: ...


class RecordUnreadableError(RuntimeError):
    """The record could not be read, so there is nothing to decide on.

    Raised rather than returned empty, and that distinction is the whole
    point. Empty context reads to a model as a beamline where nothing has
    been tried, which is a sentence about the facility rather than about a
    failed request, and it would be answered confidently.
    """


class Record:
    """The keeper, for the questions a profile asks before it decides."""

    def __init__(self, config_path: str | None = None, http: Any = None) -> None:
        path = config_path or os.environ.get(CONFIG_VARIABLE)
        if not path:
            raise RecordUnreadableError(
                f"{CONFIG_VARIABLE} names no file, so this profile cannot reach the "
                "record. The unit sets it to the same configuration the service reads."
            )
        config = load(Path(path))
        self._base = config.base_url.rstrip("/")
        self._token = config.token
        self._http = http if http is not None else httpx

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            answered = self._http.get(
                f"{self._base}{path}",
                params=dict(params or {}),
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=TIMEOUT,
            )
        except Exception as unreachable:
            raise RecordUnreadableError(f"GET {path}: {unreachable}") from unreachable
        if answered.status_code != 200:
            raise RecordUnreadableError(f"GET {path}: {answered.status_code}")
        return answered.json()

    def operation_schema(self, operation_id: str) -> Mapping[str, Any]:
        """The parameters an operation accepts, and their bounds.

        The most valuable of the three. Without it a model is guessing at
        names and ranges, and a proposal whose parameters fail the schema
        is refused by the keeper rather than quietly accepted, so guessing
        costs a whole thinking.
        """
        operation = self._get(f"/operations/{operation_id}")
        schema: Mapping[str, Any] = operation.get("parameters_schema") or {}
        return schema

    def execution(self, execution_id: str) -> Mapping[str, Any]:
        """One execution as the record holds it, for the facts a case drops.

        Two of them, and both were got wrong by inferring instead of
        reading. Where the work ran is here and not in a case, because an
        inquiry names an execution and the beamline is the execution's
        fact. And the id of each step as it was walked is here, which is
        not the id a case carries: a case is built from the procedure, so
        its steps are the composed ones, and anything registered against
        a walked step is found by the walked step's id.
        """
        answered: Mapping[str, Any] = self._get(f"/executions/{execution_id}")
        return answered

    def prior_runs(self, beamline: str, limit: int = 10) -> Sequence[Mapping[str, Any]]:
        """What has been dispatched at this beamline lately, and how it ended.

        Newest first and bounded, because this goes into a prompt. The
        bound is here rather than at the caller so that a profile cannot
        accidentally ask for the whole facility.
        """
        listed = self._get("/executions", {"beamline": beamline, "limit": min(limit, 25)})
        items: Sequence[Mapping[str, Any]] = listed.get("items") or []
        return items

    def datasets_for(self, step_id: str) -> Sequence[Mapping[str, Any]]:
        """What one step actually produced, if anything.

        By step and not by execution, because that is what the listing
        filters on: a dataset is registered against the step that
        produced it, and an execution's datasets are its steps' put
        together.

        A run that ended well and recorded nothing is the shape this
        system was built to notice, and a strategy that cannot see it
        would go on asking for more of a run whose output nobody kept.
        """
        listed = self._get("/datasets", {"step_id": step_id})
        items: Sequence[Mapping[str, Any]] = listed.get("items") or []
        return items

    def procedure(self, procedure_id: str) -> Mapping[str, Any]:
        """What a run was asked to do, which is where the parameters are.

        An execution does not carry them. Its steps say how each one
        ended and point back here with `procedure_step_id`, and the
        keeper's own response says the operation, the parameters and the
        devices are all on the procedure, and that `describes` is not to
        be taken apart to recover them.

        Asked for one procedure rather than a list, because the caller
        wants the one a particular run used and runs can share one:
        19-BM has dispatched thirty-nine executions across eight
        procedures, so a caller that remembers what it has already read
        asks a fifth as often over that whole history. Over a recent
        window it saves less, for the reason the caller's own cache
        states.
        """
        answered: Mapping[str, Any] = self._get(f"/procedures/{procedure_id}")
        return answered


__all__ = ["CONFIG_VARIABLE", "Reading", "Record", "RecordUnreadableError"]
