#!/usr/bin/env python3
"""Watch a keeper's event log go by, in a terminal.

The first reader of `GET /events`, and the reason that route exists before
any web page does. A page is a project; this is a file, and what it is for
is finding out whether the event vocabulary reads well at a glance before
anybody spends a project on it.

    CORA_KEEPER_URL=https://keeper.example:8000 \\
    CORA_TOKEN=$(cat ~/.cora/token) \\
    tools/cora_tail.py --beamline 7-bm

Standard library only, on purpose. It has no lockfile, no package and no
install, so getting it to a beamline is copying one file to a host that
has Python. That is the whole delivery story and it is the right one for
something meant to answer a question and possibly be deleted.

## Seed, then fold

Three events in the whole log carry a beamline, and each of them opens a
stream: a dispatch, a pursuit starting and a device being registered.
Nothing that follows one carries it. Not a claim, not a step outcome, not
an engine report, not a round opening or closing, and nothing in Counsel
or Custody at all.

So the beamline is a fact about the stream rather than about the event,
which is why the server does not filter on it and why this attributes
events itself.

It learns in two ways. At startup it reads `GET /executions` for the
executions already open, which is what lets a tail started mid-scan say
anything about that scan. Then every stream-opening event that goes by
teaches it one more.

What it attributes is the opened stream and, through `correlation_id`,
the events on other streams that belong to the same round.

## The limit of that, stated rather than hidden

An inquiry and a proposal commit before the dispatch that says where the
work goes. A tail cannot attribute those when they arrive, because the
fact that would attribute them has not happened yet.

So `--beamline` drops them, and running with no filter is what shows a
whole round. That is a property of the log and not a defect here: the
alternative is buffering every unattributed event forever in case a later
one explains it.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_URL = "http://localhost:8000"
WAIT_SECONDS = 30
PAGE_LIMIT = 200
SEED_LIMIT = 100
"""What `GET /executions` accepts, which is lower than this reads from the log."""
SOCKET_TIMEOUT = WAIT_SECONDS + 15
"""Longer than the server's hold, so the server ends the wait and not us.

A client timing out first turns an ordinary empty answer into an error
and loses the cursor's place in the bargain.
"""

UNATTRIBUTED = ".."
"""Shown where no beamline is known, which is not the same as none."""

_PAYLOAD_DETAIL: dict[str, tuple[str, ...]] = {
    "ExecutionDispatched": ("procedure_name",),
    "ExecutionStepDone": ("index", "engine_reference"),
    "ExecutionStepRefused": ("index",),
    "ExecutionStepBroken": ("index", "cause"),
    "ExecutionStepSkipped": ("index",),
    "ExecutionStepEngineStarted": ("engine_reference",),
    "InquiryMade": ("objective",),
    "InquiryAnswered": ("conclusion",),
    "OperationDefined": ("operation_name",),
    "ProcedureDefined": ("procedure_name",),
    "DatasetRegistered": ("external_ref_value",),
    "DatasetManifestRegistered": ("convention",),
    "DeviceRegistered": ("device_name",),
    "PursuitStarted": ("goal",),
    "PursuitRoundOpened": ("round_index",),
    "PursuitRoundClosed": ("round_index", "outcome"),
}
"""Which payload fields to show per event type, in the order to show them.

A short list rather than the whole payload, because the question a tail
answers is what happened and not what every field held. An event type
absent from here shows its stream id alone, which is enough to follow it
and is what `--json` is for when it is not.
"""


OPENS_A_STREAM = frozenset({"ExecutionDispatched", "PursuitStarted", "DeviceRegistered"})
"""The three events that carry a beamline, each one opening a stream.

Every later event on that stream carries none, so what the beamline
describes is the stream. A fourth event type growing the field belongs
here, and until it does its stream reads as unattributed rather than
wrong.
"""


class Attribution:
    """Which beamline each stream and each correlation belongs to.

    A fold over the log, held in the client because the server will not
    do it: a beamline is a fact about a stream, and the join from a
    stream to the other streams of one round is the correlation id.
    """

    def __init__(self) -> None:
        self._by_stream: dict[str, str] = {}
        self._by_correlation: dict[str, str] = {}

    def learn_stream(self, stream_id: str, beamline: str) -> None:
        self._by_stream[stream_id] = beamline

    def observe(self, event: dict[str, Any]) -> None:
        """Take whatever this event teaches about where work is running."""
        if str(event.get("event_type")) not in OPENS_A_STREAM:
            return
        beamline = (event.get("payload") or {}).get("beamline")
        if isinstance(beamline, str):
            self._by_stream[str(event["stream_id"])] = beamline
            self._by_correlation.setdefault(str(event["correlation_id"]), beamline)

    def beamline_for(self, event: dict[str, Any]) -> str | None:
        """The beamline this event belongs to, or None if nothing says."""
        known = self._by_stream.get(str(event["stream_id"]))
        if known is not None:
            self._by_correlation.setdefault(str(event["correlation_id"]), known)
            return known
        return self._by_correlation.get(str(event["correlation_id"]))


def summarise(event: dict[str, Any]) -> str:
    """One line's worth of what this event says, after its type."""
    payload: dict[str, Any] = event.get("payload") or {}
    parts: list[str] = [str(event["stream_id"])[-8:]]
    for key in _PAYLOAD_DETAIL.get(str(event["event_type"]), ()):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value)
        parts.append(text if len(text) <= 48 else text[:45] + "...")
    return "  ".join(parts)


def format_row(event: dict[str, Any], beamline: str | None) -> str:
    """One aligned line: when, where, what, and which."""
    clock = str(event["occurred_at"])[11:19]
    where = (beamline or UNATTRIBUTED).ljust(6)
    return f"  {clock}  {where}  {str(event['event_type']).ljust(28)}  {summarise(event)}"


def _request(url: str, token: str | None, timeout: float, context: ssl.SSLContext) -> Any:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode())


def seed(
    base_url: str, token: str | None, beamline: str | None, context: ssl.SSLContext
) -> Attribution:
    """Learn the open executions before tailing, so a mid-scan start reads.

    A tail that skipped this would show every step of a scan already
    running as unattributed, because the dispatch that named its beamline
    went past before anybody was watching.
    """
    known = Attribution()
    query = {"limit": str(SEED_LIMIT)}
    if beamline is not None:
        query["beamline"] = beamline
    url = f"{base_url}/executions?{urllib.parse.urlencode(query)}"
    try:
        page = _request(url, token, timeout=30, context=context)
    except urllib.error.HTTPError as error:
        print(f"could not read executions to seed from: {error}", file=sys.stderr)
        return known
    for summary in page.get("items", []):
        known.learn_stream(str(summary["execution_id"]), str(summary["beamline"]))
    return known


def run(args: argparse.Namespace) -> int:
    base_url = args.url.rstrip("/")
    context = ssl.create_default_context(cafile=args.ca)
    token = _read_token(args)
    known = seed(base_url, token, args.beamline, context)
    cursor: str | None = args.after

    while True:
        query: dict[str, str] = {"limit": str(PAGE_LIMIT), "wait": str(WAIT_SECONDS)}
        if cursor is not None:
            query["after"] = cursor
        url = f"{base_url}/events?{urllib.parse.urlencode(query)}"
        try:
            page = _request(url, token, timeout=SOCKET_TIMEOUT, context=context)
        except urllib.error.HTTPError as error:
            print(f"{error.code} from the keeper: {error.reason}", file=sys.stderr)
            return 1
        except (TimeoutError, urllib.error.URLError) as error:
            print(f"could not reach the keeper: {error}", file=sys.stderr)
            return 1
        except ssl.SSLError as error:
            print(
                f"TLS failed: {error}\nA deployment signed by its own CA needs "
                "--ca pointing at that certificate.",
                file=sys.stderr,
            )
            return 1

        for event in page.get("items", []):
            known.observe(event)
            beamline = known.beamline_for(event)
            if args.beamline is not None and beamline != args.beamline:
                continue
            if args.json:
                print(json.dumps(event))
            else:
                print(format_row(event, beamline))
        sys.stdout.flush()

        if page.get("next_cursor") is not None:
            cursor = page["next_cursor"]


def _read_token(args: argparse.Namespace) -> str | None:
    """The bearer token, from a file if one was named.

    A file is the better of the two and the default on a host: a token
    lives at mode 600 in its caller's home, and reading it here keeps it
    out of the environment and out of anybody's process listing.
    """
    if args.token_file:
        with open(args.token_file, encoding="utf-8") as handle:
            return handle.read().strip()
    token: str | None = args.token
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cora_tail.py",
        description="Watch a keeper's event log go by.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("CORA_KEEPER_URL", DEFAULT_URL),
        help="Where the keeper is. Defaults to CORA_KEEPER_URL, then localhost.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CORA_TOKEN"),
        help="Bearer token. Defaults to CORA_TOKEN. Omitted where the deployment "
        "has no rulebook configured, which is the development posture.",
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("CORA_TOKEN_FILE"),
        help="Read the bearer token from this file rather than the environment. "
        "What a deployment has: tokens sit at mode 600 in their caller's home.",
    )
    parser.add_argument(
        "--ca",
        default=os.environ.get("CORA_CA"),
        help="The CA certificate the keeper's TLS is signed by. Needed for a "
        "deployment using its own CA rather than a public one.",
    )
    parser.add_argument(
        "--beamline",
        default=None,
        help="Show only what can be attributed to this beamline, such as 7-bm. "
        "The opening events of a round commit before anything names a beamline, "
        "so a filter drops them; run with none to watch a whole round.",
    )
    parser.add_argument(
        "--after",
        default=None,
        help="Resume from a cursor a previous response returned. Omitted starts "
        "at the beginning of the log.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="One raw event per line, for a pipe rather than a person.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
