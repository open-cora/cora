"""Does the vendor client put anything on the wire that httpx could not?

The store spike found that an adapter does not need the store's client
library, because the same key came off the raw HTTP surface byte for byte.
This asks the same question of the data management service, and it matters
more here: that client disables certificate verification unconditionally,
so anything importing it talks to an unauthenticated server no matter what
the caller does.

The method is a stub that records exactly what it was sent, driven twice.
Once by the vendor client, once by a reimplementation over httpx. If the
two recordings match, the reimplementation is a faithful client and the
vendor package can stay out of the dependency tree.

Run it:

    uv run --no-project --with decorator --with httpx \\
        python spikes/dm_adapter/compare.py

The vendor package is not on PyPI, so point PYTHONPATH at an extracted
copy of the conda package, or set DM_SITE_PACKAGES to where it lives. The
script says what it could not find rather than guessing.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

STATION = "2bm"
EXPERIMENT = "tomo-2026-1"
USERNAME = "dmuser"
PASSWORD = "dmpass"
SESSION_COOKIE = "SESSIONID=stub-session-1; expires=Mon, 22 Sep 2036 12:00:00 GMT"


@dataclass
class Recorded:
    """One request as the server received it, before any client parsed it."""

    method: str
    path: str
    body: str
    content_type: str | None
    cookie: str | None

    def key(self) -> tuple[str, str, str, str | None, str | None]:
        return (self.method, self.path, self.body, self.content_type, self.cookie)


@dataclass
class Journal:
    requests: list[Recorded] = field(default_factory=list)
    fail_reads_with: tuple[int, str] | None = None


DM_STATUS_OBJECT_NOT_FOUND = 14


def _handler_for(journal: Journal) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            return

        def _record(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            journal.requests.append(
                Recorded(
                    method=self.command,
                    path=self.path,
                    body=raw.decode("utf-8", "replace"),
                    content_type=self.headers.get("Content-Type"),
                    cookie=self.headers.get("Cookie"),
                )
            )

        def _respond(
            self,
            payload: object,
            *,
            set_cookie: bool = False,
            failure: tuple[int, str] | None = None,
        ) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if failure is None:
                self.send_header("Dm-Status-Code", "0")
            else:
                code, message = failure
                self.send_header("Dm-Status-Code", str(code))
                self.send_header("Dm-Status-Message", message)
            if set_cookie:
                self.send_header("Set-Cookie", SESSION_COOKIE)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self._record()
            self._respond({"status": "ok"}, set_cookie=self.path.endswith("/login"))

        def do_GET(self) -> None:
            self._record()
            self._respond(
                {
                    "id": 4210,
                    "name": EXPERIMENT,
                    "experimentStation": {"name": STATION},
                    "storageDirectory": f"/data/{STATION}/{EXPERIMENT}",
                },
                failure=journal.fail_reads_with,
            )

    return Handler


def serve(journal: Journal) -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _handler_for(journal))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def dm_encode(value: str) -> str:
    """Reproduce the vendor path encoder, including the leak.

    It base64-encodes twice, deliberately, so that a '+' in the first
    result cannot be read as a space after one decode. What is not
    deliberate is the return type: the result is `bytes`, and every call
    site interpolates it into an f-string, so the Python repr of a bytes
    object reaches the URL. A path segment therefore arrives at the server
    spelled b'...', quotes and all, and the vendor decoder strips that
    prefix back off. Both halves depend on it, so a reimplementation has
    to reproduce it rather than fix it.
    """
    once = base64.encodebytes(str(value).encode())
    twice = base64.b64encode(once)
    return repr(twice)


def via_vendor(base_url: str, *, strict: bool = False) -> str | None:
    site = os.environ.get("DM_SITE_PACKAGES")
    if site:
        sys.path.insert(0, site)
    try:
        from dm.ds_web_service.api.experimentDsApi import ExperimentDsApi
    except ImportError as exc:
        return f"vendor client not importable ({exc})"

    api = ExperimentDsApi(username=USERNAME, password=PASSWORD, url=base_url)
    try:
        api.getExperimentByName(EXPERIMENT, STATION)
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise
        return f"vendor client raised after its requests were sent: {exc!r}"
    return None


class DmError(RuntimeError):
    """A failure the service reported in headers rather than in its status line."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Dm-Status-Code {code}: {message}")


def raise_for_dm_status(response: Any) -> None:
    """The half of a faithful client that is easy to leave out.

    The service answers 200 with a body and puts the failure in
    `Dm-Status-Code`, so a client that checks only the HTTP status treats
    every error as a successful read of nonsense. There is no version of
    this that is safe to skip.
    """
    code = response.headers.get("Dm-Status-Code")
    if code is None or int(code) == 0:
        return
    raise DmError(int(code), response.headers.get("Dm-Status-Message", "Internal Error"))


def via_httpx(base_url: str) -> str | None:
    try:
        import httpx
    except ImportError as exc:
        return f"httpx not importable ({exc})"

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        login = client.post(
            "/dm/login",
            data={"username": USERNAME, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        raise_for_dm_status(login)
        cookie = login.headers.get("Set-Cookie")
        if cookie is None:
            return "stub returned no Set-Cookie on login"

        read = client.get(
            f"/dm/experimentsByName/{dm_encode(EXPERIMENT)}/{STATION}",
            headers={"Cookie": cookie, "Content-Type": "html"},
        )
        raise_for_dm_status(read)
    return None


def describe_failure(run: Any, base_url: str) -> str:
    """What a client does when the service reports a failure in a header."""
    try:
        note = run(base_url)
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}: {exc}"
    if note:
        return f"returned early: {note}"
    return "returned normally, treating the failure as a successful read"


def render(title: str, journal: Journal) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    if not journal.requests:
        print("  (nothing recorded)")
    for i, r in enumerate(journal.requests, start=1):
        print(f"  {i}. {r.method} {r.path}")
        print(f"     content-type: {r.content_type}")
        print(f"     cookie:       {r.cookie}")
        print(f"     body:         {r.body!r}")


def main() -> int:
    vendor_journal = Journal()
    server, base_url = serve(vendor_journal)
    vendor_note = via_vendor(base_url)
    server.shutdown()

    httpx_journal = Journal()
    server, base_url = serve(httpx_journal)
    httpx_note = via_httpx(base_url)
    server.shutdown()

    print("What the stub was sent, by each client")
    print("=" * 38)
    if vendor_note:
        print(f"\nvendor: {vendor_note}")
    if httpx_note:
        print(f"\nhttpx: {httpx_note}")

    render("vendor client", vendor_journal)
    render("httpx reimplementation", httpx_journal)

    print("\nVerdict")
    print("-------")
    if not vendor_journal.requests or not httpx_journal.requests:
        print("  Inconclusive: one side sent nothing. See the notes above.")
        return 2

    vendor_keys = [r.key() for r in vendor_journal.requests]
    httpx_keys = [r.key() for r in httpx_journal.requests]
    if vendor_keys == httpx_keys:
        print("  Identical. Every request matches on method, path, body,")
        print("  content type and cookie, so the vendor package buys nothing")
        print("  on the wire that httpx cannot send.")
        return 0

    print("  They differ. The first mismatch:")
    for i, (a, b) in enumerate(zip(vendor_keys, httpx_keys), start=1):
        if a != b:
            print(f"    request {i}")
            print(f"      vendor: {a}")
            print(f"      httpx:  {b}")
            break
    if len(vendor_keys) != len(httpx_keys):
        print(f"    counts differ: vendor {len(vendor_keys)}, httpx {len(httpx_keys)}")
    return 1


def compare_failure_handling() -> None:
    """The same two clients, against a service reporting a failure in a header."""
    failure = (DM_STATUS_OBJECT_NOT_FOUND, "Experiment tomo-2026-1 not found.")

    print("\n\nWhen the service reports a failure with HTTP 200")
    print("=" * 47)
    print(f"  stub answers 200 with Dm-Status-Code: {failure[0]}\n")

    for title, run in (("vendor client", lambda u: via_vendor(u, strict=True)), ("httpx", via_httpx)):
        journal = Journal(fail_reads_with=failure)
        server, base_url = serve(journal)
        print(f"  {title+':':16} {describe_failure(run, base_url)}")
        server.shutdown()

    print("\n  A client that checks only the HTTP status line sees 200 and a")
    print("  JSON body, so the failure arrives as data. Reproducing the header")
    print("  check is not optional.")


if __name__ == "__main__":
    status = main()
    compare_failure_handling()
    raise SystemExit(status)
