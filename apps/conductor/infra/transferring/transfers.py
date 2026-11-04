"""A transfer engine that moves files with Globus, for the facility that runs it.

`conductor.adapters.globus_transfer` declares what it needs of a transfer
service and imports nothing, so something has to be the thing that
actually speaks to one. This is that, and it lives here rather than in
the package for the reason every profile does: it depends on a service
one facility happens to use, and three of the four beamlines this system
serves will never move a byte through it.

`run.profile` names `transfers:engine`, and the entrypoint imports it before
it reads anything else, so a deployment that cannot import this stops at
startup rather than at the first transfer.

## Two builders, because an engine binds one direction

`GlobusTransfer` is given a source collection and a destination
collection when it is built, and a step may name neither, so one engine
moves files one way and only one way. A chain that sends a dataset to a
computing facility and brings the result back needs both ways, and that
is two engines rather than one engine used twice.

So this module builds either. `engine` is the trip out and `homeward` is
the trip back, each reading its own family of variables, and a
deployment that wants both names both in its run tables.

Two engines can be wired wrong in two ways and only one of them is
noticed. `Repertoire` refuses two engines offering one routine, so the
pair cannot answer to the same name. Nothing at runtime notices the
other: a return leg reading the outbound variables would move the result
from the beamline to the facility a second time and report success, with
the record saying a result came home. `Direction` is what makes the two
families nameable apart, and
`tests/test_each_transfer_direction_reads_its_own_settings.py` is what
checks they stayed apart.

## Two settings and a credential, none of them here

The collections and the destination prefix come from the environment the
unit sets, the way the thinker's profiles take theirs. They are a
deployment's facts: which collection a beamline publishes and where its
data is staged are not things a procedure should be able to name, and
`GlobusTransfer` refuses to take them from a step for that reason.

The credential is not a setting at all. `alcf_tokens` holds the
facility's Globus tokens and hands back an authorizer that refreshes,
which is what a process running for weeks needs and what a client built
once at startup could not do: an access token outlives a command and
does not outlive a service.

## Why the authorizer is built once and the client per engine

Building the authorizer reads a token store from disk. Doing it per
transfer would read that file on every step of every procedure, and the
authorizer already refreshes on its own, so there is nothing to gain by
rebuilding it.

## What this does not do

It does not retry. A transfer the service refuses is reported as refused
and a transfer still running when the bound expires is handed off, and
both of those are decisions the engine seam already makes. Something
here that tried again would be a second policy competing with the walk's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from alcf_tokens.auth import get_service_authorizer
from globus_sdk import TransferClient, TransferData

from conductor.adapters.globus_transfer import FAILED, SUCCEEDED, GlobusTransfer, Item
from conductor.seams import Said

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class Direction:
    """One way files move, and the variables a deployment sets to say where.

    An engine binds its two collections when it is built, so the trip out
    and the trip home are two engines, and one process holds one
    environment. Each direction therefore names its own family of
    variables rather than sharing a family and being told apart some
    other way.

    The alternative was a second profile module, and what differs between
    the two is six strings. A copy would be a second home for the fault
    this profile has already had once, which was in `GlobusTransfers.state`.
    """

    source: str
    destination: str
    prefix: str
    routine: str
    settle: str
    default_routine: str


OUTBOUND: Final = Direction(
    source="CORA_TRANSFER_SOURCE",
    destination="CORA_TRANSFER_DESTINATION",
    prefix="CORA_TRANSFER_PREFIX",
    routine="CORA_TRANSFER_ROUTINE",
    settle="CORA_TRANSFER_SETTLE_SECONDS",
    default_routine="transfer",
)
"""A beamline's data on its way to the facility that will compute on it.

Its variables keep the spelling they had when this module built one
engine, so a host already running a transfer leg needs no edit.
"""

HOMEWARD: Final = Direction(
    source="CORA_RETRIEVE_SOURCE",
    destination="CORA_RETRIEVE_DESTINATION",
    prefix="CORA_RETRIEVE_PREFIX",
    routine="CORA_RETRIEVE_ROUTINE",
    settle="CORA_RETRIEVE_SETTLE_SECONDS",
    default_routine="retrieve",
)
"""A result on its way back, which is the first of these to end at a beamline.

The prefix is where results land under the beamline's own collection,
and it is a deployment's fact for exactly the reason the outbound one
is: a step able to name it could write anywhere the collection reaches.
"""

DEFAULT_SETTLE_SECONDS: Final = 600.0
"""How long a walk waits before handing a transfer off.

Ten minutes. Long enough that a small file finishes inside it and the
record carries one step rather than a step and a resolution, short enough
that a large one does not hold a claim for an afternoon. Nothing is lost
by guessing low: a handoff is an outcome rather than a failure.
"""

SERVICE: Final = "globus-transfer"
"""Which of the facility's stored tokens this asks for."""

HOPELESS: Final = frozenset(
    {
        "FILE_NOT_FOUND",
        "PERMISSION_DENIED",
        "NO_CREDENTIALS",
        "EXPIRED_CREDENTIALS",
        "AUTHENTICATION_FAILED",
        "ENDPOINT_NOT_FOUND",
        "QUOTA_EXCEEDED",
        "SUBJECT_ALT_NAME_MISMATCH",
    }
)
"""Faults that waiting will not cure, so the walk stops waiting.

Transfer retries everything until the task's deadline, which is a day
after it was asked for, and a missing file is retried exactly as
patiently as a busy endpoint. The ones here cannot come right on their
own: the file is absent, or this identity may not read it.

What is deliberately absent is as considered as what is here.
CONNECTION_FAILED, ENDPOINT_TOO_BUSY and a paused endpoint are all
states a transfer recovers from, and treating them as failures would
turn a slow afternoon into a procedure that refused.

A task reported failed this way is still running at the service until
its deadline. Nothing here cancels it, for the reason the adapter
gives: a walk's verdict is a fact about this process and not about the
work. A deployment that wants them reaped does it from outside.
"""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set, so this transfer engine does not know which "
            "collection to use. The unit file sets it."
        )
    return value


@dataclass(frozen=True, slots=True)
class GlobusTransfers:
    """Submitting a move and asking after it, over the Globus Transfer API.

    The two methods `Transferring` declares, and nothing else. Every item
    of one step goes out as a single task, so one step is one reference
    and a watcher resolving it later has one thing to ask about.
    """

    client: TransferClient

    def submit(
        self,
        *,
        source: str,
        destination: str,
        items: Sequence[Item],
        label: str | None,
    ) -> str:
        data = TransferData(source_endpoint=source, destination_endpoint=destination, label=label)
        for item in items:
            data.add_item(item.source_path, item.destination_path)
        submitted: Any = self.client.submit_transfer(data)
        return str(submitted["task_id"])

    def state(self, reference: str) -> Said:
        """What Transfer says, with a fault it will never recover from read as a failure.

        The status alone is not enough, and that is measured rather than
        assumed. A transfer whose source file does not exist sits in
        ACTIVE for a whole day, accumulating faults, retrying something
        that cannot work, with the reason only in `nice_status`. An
        engine told only the status waits out its bound and hands the
        work off, so a broken transfer and a large one end the same way
        and the record never says which happened.

        Which faults are worth waiting through is service knowledge, so
        the list is here rather than in the adapter.
        """
        task: Any = self.client.get_task(reference)
        status = str(task["status"])
        fault = str(task.get("nice_status") or "")

        if status in (SUCCEEDED, FAILED):
            return Said(status, fault or str(task.get("nice_status_short_description") or ""))
        if fault in HOPELESS:
            return Said(FAILED, f"{fault} after {task.get('faults')} attempts")
        return Said(status, fault)


def engine() -> GlobusTransfer:
    """Build the engine that moves a beamline's data out."""
    return _built(OUTBOUND)


def homeward() -> GlobusTransfer:
    """Build the engine that brings a result back."""
    return _built(HOMEWARD)


def _built(way: Direction) -> GlobusTransfer:
    """One engine, bound to the collections its direction names.

    A deployment running both reads the token store twice at startup,
    once per engine, which is the cost of not sharing a client between
    them. It is paid once and the authorizer refreshes itself from then
    on, so there is nothing here worth the coupling that avoiding it
    would need.
    """
    settle = os.environ.get(way.settle, "").strip()
    return GlobusTransfer(
        transfers=GlobusTransfers(
            client=TransferClient(authorizer=get_service_authorizer(SERVICE))
        ),
        routines=frozenset({os.environ.get(way.routine, "").strip() or way.default_routine}),
        source=_required(way.source),
        destination=_required(way.destination),
        destination_prefix=_required(way.prefix),
        settle_timeout=float(settle) if settle else DEFAULT_SETTLE_SECONDS,
    )
