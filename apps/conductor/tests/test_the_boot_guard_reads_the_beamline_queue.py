"""The boot guard holds a conductor while work waits at its beamline, and only reads.

`infra/deploy/nothing-is-waiting.sh` is what the after-boot job runs before
it starts a conductor nobody started. It is handed the unit's name, reads
the interpreter, the configuration and the certificate bundle out of that
unit, and asks the keeper, as that conductor, for the executions dispatched
to its beamline and not yet taken up.

These run the script itself, against a unit rendered from the template the
installer renders and a keeper that is a few lines of `http.server` on the
loopback. Rendering the real template is the point: the guard finds the
configuration by reading the unit, so a change to how the unit names it is
a change the guard has to survive. The interpreter the unit names is a
wrapper around the one running this suite, which has this package and its
HTTP client installed, the way a deployed virtualenv does.

## Why a crash must not read as work waiting

The job holds a conductor on any refusal, so a guard that crashed would
hold it too, and nobody would see a difference after a boot. The installer
does see one: it refuses a guard that answers 2 and accepts 1 as work that
happens to be waiting. A crash surfacing as 1 would pass the installer and
then hold the conductor after every boot the job acts on, so the last case
below breaks the question on purpose and expects 2.
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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlsplit

import certifi
import pytest

from conductor.adapters.http_tasking import DISPATCHED

if TYPE_CHECKING:
    from collections.abc import Iterator

DEPLOY = Path(__file__).resolve().parents[1] / "infra" / "deploy"
GUARD = DEPLOY / "nothing-is-waiting.sh"

BEAMLINE = "7-bm"
TOKEN = "the-conductors-own-token"
UNIT = "conductor.service"
"""A stand-in for the deployed name, which the guard reads from its argument."""

_PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")


@dataclass(frozen=True)
class Request:
    """One request the stand-in keeper received."""

    method: str
    path: str
    query: dict[str, list[str]]
    authorization: str | None


class Keeper(ThreadingHTTPServer):
    """The part of the keeper's API the guard reaches, answering as told."""

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
        page = {"items": keeper.items, "next_cursor": keeper.next_cursor}
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


@pytest.fixture
def keeper() -> Iterator[Keeper]:
    server = Keeper()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _home(tmp_path: Path, *, base_url: str, python: str | None = None) -> Path:
    """A home holding a conductor's unit, rendered from the shipped template."""
    app = tmp_path / "app"
    _executable(app / ".venv" / "bin" / "python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    etc = tmp_path / "etc"
    etc.mkdir()
    config = etc / "conductor.toml"
    config.write_text(
        f'beamline = "{BEAMLINE}"\n\n[keeper]\nbase_url = "{base_url}"\ntoken = "{TOKEN}"\n',
        encoding="utf-8",
    )
    bundle = etc / "ca-bundle.crt"
    shutil.copyfile(certifi.where(), bundle)

    templates = sorted(DEPLOY.glob("*.service.in"))
    assert len(templates) == 1, f"expected the one conductor template beside the guard: {templates}"
    unit = templates[0].read_text(encoding="utf-8")
    for placeholder, value in {
        "@BEAMLINE@": BEAMLINE,
        "@INSTANCE_SUFFIX@": "",
        "@DEPLOY_HOST@": "this-host",
        "@APP_DIR@": str(app),
        "@CONFIG@": str(config),
        "@CA_BUNDLE@": str(bundle),
        "@PROFILE_ENVIRONMENT@": "",
        "@RUN_ENVIRONMENT@": "",
        "@EPICS_ENVIRONMENT@": "",
    }.items():
        unit = unit.replace(placeholder, value)
    assert not _PLACEHOLDER.findall(unit), "the template gained a placeholder this does not fill"
    if python is not None:
        unit = unit.replace(f"{app}/.venv/bin/python3", python)

    home = tmp_path / "home"
    units = home / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / UNIT).write_text(unit, encoding="utf-8")
    return home


def _guard(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD), *arguments],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _dispatched(execution_id: str, created_at: str) -> dict[str, str]:
    return {
        "execution_id": execution_id,
        "procedure_id": "00000000-0000-0000-0000-000000000000",
        "procedure_name": "align_then_scan",
        "beamline": BEAMLINE,
        "status": DISPATCHED,
        "created_at": created_at,
        "updated_at": created_at,
    }


def test_nothing_dispatched_lets_the_conductor_start(tmp_path: Path, keeper: Keeper) -> None:
    home = _home(tmp_path, base_url=keeper.base_url)

    done = _guard(home, UNIT)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "nothing is dispatched" in done.stdout


def test_the_guard_asks_as_the_conductor_about_its_beamline_and_only_reads(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.items = [_dispatched("a1", "2026-11-09T09:58:00Z")]
    home = _home(tmp_path, base_url=keeper.base_url)

    _guard(home, UNIT)

    assert keeper.received == [
        Request(
            method="GET",
            path="/executions",
            query={"beamline": [BEAMLINE], "status": [DISPATCHED]},
            authorization=f"Bearer {TOKEN}",
        )
    ], "the guard asked for something other than this beamline's untaken work, or wrote"


def test_work_dispatched_and_waiting_holds_the_conductor_and_names_each_execution(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.items = [
        _dispatched("the-newer-one", "2026-11-09T10:30:00Z"),
        _dispatched("the-older-one", "2026-11-09T09:58:00Z"),
    ]
    home = _home(tmp_path, base_url=keeper.base_url)

    done = _guard(home, UNIT)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "2 execution(s) are dispatched to 7-bm" in done.stdout
    assert done.stdout.index("the-older-one") < done.stdout.index("the-newer-one"), (
        "the hold lists the work oldest first, so whoever reads it sees how long it has waited"
    )


def test_a_token_the_keeper_refuses_reads_as_a_queue_that_could_not_be_read(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.status = 403
    home = _home(tmp_path, base_url=keeper.base_url)

    done = _guard(home, UNIT)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "could not be read" in done.stdout
    assert "403" in done.stdout


def test_a_keeper_that_cannot_be_reached_reads_as_a_queue_that_could_not_be_read(
    tmp_path: Path,
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home = _home(tmp_path, base_url=f"http://127.0.0.1:{port}")

    done = _guard(home, UNIT)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "could not be read" in done.stdout


def test_a_unit_that_names_no_configuration_is_held_rather_than_started(tmp_path: Path) -> None:
    home = _home(tmp_path, base_url="http://127.0.0.1:9")
    unit = home / ".config" / "systemd" / "user" / UNIT
    unit.write_text(re.sub(r" --config \S+", "", unit.read_text(encoding="utf-8")), "utf-8")

    done = _guard(home, UNIT)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "names no configuration" in done.stdout


def test_a_guard_asked_about_no_unit_holds_rather_than_guessing(tmp_path: Path) -> None:
    done = _guard(tmp_path)

    assert done.returncode == 2, done.stdout + done.stderr


def test_a_question_that_crashes_reads_as_could_not_read_rather_than_work_waiting(
    tmp_path: Path,
) -> None:
    crashing = tmp_path / "crashing-python"
    _executable(crashing, "#!/bin/sh\necho Traceback >&2\nexit 1\n")
    home = _home(tmp_path, base_url="http://127.0.0.1:9", python=str(crashing))

    done = _guard(home, UNIT)

    assert done.returncode == 2, (
        f"a crash came back as {done.returncode}. As 1 it would pass the installer, "
        "which accepts work waiting, and then hold the conductor after every boot"
    )
    assert "failed" in done.stdout
