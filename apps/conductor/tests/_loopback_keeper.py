"""A keeper on the loopback, and a unit rendered the way an installer renders it.

Two guards ask the keeper something before the after-boot job may start the
unit they stand beside: the conductor's asks what is dispatched to its
beamline, and the turner's asks which pursuits are running. Both read the
interpreter, the configuration and the certificate bundle out of the unit
they are handed, so both are tested against a unit rendered from the
template its installer renders, and against a keeper that is a few lines of
`http.server` answering one page of whatever it is asked for.

The interpreter such a unit names is a wrapper around the one running this
suite, which has this package and its HTTP client installed, the way a
deployed virtualenv does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlsplit

import certifi

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

_PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")


@dataclass(frozen=True)
class Request:
    """One request the stand-in keeper received."""

    method: str
    path: str
    query: dict[str, list[str]]
    authorization: str | None


class Keeper(ThreadingHTTPServer):
    """The part of the keeper's API a guard reaches, answering as told.

    A listing answers with the items whose status it asked for, as the
    keeper's filter does, so a guard that asks one status at a time sees
    each item once. An item that names no status answers every ask.
    """

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Answering)
        self.status = 200
        self.items: list[dict[str, str]] = []
        self.next_cursor: str | None = None
        self.received: list[Request] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _Answering(BaseHTTPRequestHandler):
    def _keeper(self) -> Keeper:
        return cast("Keeper", self.server)

    def _received(self, method: str) -> None:
        parsed = urlsplit(self.path)
        self._keeper().received.append(
            Request(method, parsed.path, parse_qs(parsed.query), self.headers.get("Authorization"))
        )

    def do_GET(self) -> None:
        self._received("GET")
        keeper = self._keeper()
        wanted = parse_qs(urlsplit(self.path).query).get("status")
        items = [
            item
            for item in keeper.items
            if wanted is None or "status" not in item or item["status"] in wanted
        ]
        page = {"items": items, "next_cursor": keeper.next_cursor}
        body = json.dumps(page if keeper.status == 200 else {"detail": "refused"}).encode()
        self.send_response(keeper.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._received("POST")
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serving() -> Generator[Keeper]:
    """A keeper answering on the loopback until the block ends."""
    server = Keeper()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def unreachable_url() -> str:
    """An address on the loopback that nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def wrapped_python(app: Path) -> Path:
    """An interpreter where a deployment's virtualenv keeps one, running this suite's."""
    return executable(
        app / ".venv" / "bin" / "python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n'
    )


def certificate_bundle(directory: Path) -> Path:
    """A real bundle, because the HTTP client loads it whether or not it uses TLS."""
    bundle = directory / "ca-bundle.crt"
    shutil.copyfile(certifi.where(), bundle)
    return bundle


def render(template: Path, values: Mapping[str, str]) -> str:
    """The template with every placeholder filled, as its installer fills it."""
    text = template.read_text(encoding="utf-8")
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    left = _PLACEHOLDER.findall(text)
    assert not left, f"{template.name} gained placeholders this does not fill: {left}"
    return text


def installed(home: Path, unit: str, text: str) -> Path:
    """A rendered unit in the home's unit directory, where a guard looks for it."""
    path = home / ".config" / "systemd" / "user" / unit
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run(script: Path, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """A guard run the way cron runs it: a home, a path, and nothing else."""
    return subprocess.run(
        ["bash", str(script), *arguments],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
