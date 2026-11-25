#!/usr/bin/env python3
"""Watch the health of the whole installation on one page, component by component.

    uv run tools/cora_fleet.py \\
        --url https://<central-host>:8443 \\
        --token-file ~/.cora/viewer.token --ca ~/.cora/ca.crt

Then open http://127.0.0.1:8809.

The page answers whether the installation is sound enough to run a
beamtime. It leads with one sentence and four counts, says next whether
the page itself can see, draws every component where it runs, and opens
any beamline onto its components, the adapter in each seam, its data
path, the files that configure it and the commands that read it. Every
judgement is made in `fold`, which is pure; the page colours what `fold`
returns and decides nothing.

## Three sources, each on its own clock

    the tree     the registers under beamlines       read on every refresh
    the hosts    one ssh probe per beamline          every --host-interval
    the keeper   GETs over HTTPS                     every --keeper-interval

The host probe is `beamlines/verify_hosts.py`, imported rather than
copied, so the page and the command line cannot disagree about what a
host said. A host that cannot be asked is unknown and never down: an
unreachable host is the one answer that cannot be told from the truth by
reading harder.

## Components are expected, found, and remembered

A component the page has never heard of cannot be shown as missing, and a
probe that fails says nothing about what is installed. So three lists are
joined. Every beamline is expected to hold a conductor and a reporter, and
the central host its keeper, database, key server, thinker and turner,
which is the installation `docs/beamlines/index.md` describes. Whatever
else a probe finds is added and marked as found. Everything ever found is
remembered in a file outside the tree, so a host that does not answer
shows its components as unknown, with when each was last seen, rather
than as nothing at all.

## Liveness is asked where the unit runs, through the conductor's host

A beamline's unit directory is one NFS directory mounted by every host in
its account, so `is-enabled` is one answer per account and `is-active` one
per host. A unit pinned to another host is asked on that host by hopping
through the conductor's host, because a private host takes no login from
outside its beamline, and the full name a unit is pinned to bypasses
whatever routing an operator's ssh configuration gives short names.

Active is not working. A conductor whose keeper refuses it stays active
under systemd while it fails every few seconds, so the probe also asks,
from the conductor's host, whether the keeper it is configured with
answers, and counts the errors it logged in the last ten minutes. When
every conductor that asked is refused, the keeper is down whatever this
page can or cannot read from where it runs.

## It changes nothing it watches

The probes read files, ask systemctl, read the journal, and ask the
keeper's health with no credential. The keeper is asked with GETs and a
principal that may only read. Commands are printed for a person and never
run from here; the one that starts the keeper is a write and says so.
Deploying is left out on purpose: a deploy line that is right for one
beamline and pasted at another is how a station gets the wrong conductor.

## It shows coordinates, so it stays on this machine

Host names and accounts come from the untracked address book and appear
on the page, because a command central that said "the routable host"
would be no use at a terminal. So the page is served to the loopback and
nowhere else, and neither a snapshot nor the remembered inventory may be
written inside the tree where git would track it.
`beamlines/hosts.example.toml` says why that line exists.

## What it cannot see

Whether anything moved. Every check reads configuration, service state
and logs, and none of them reads a motor or asks an IOC whether it
answers.

A conductor wedged with a quiet log while its keeper answers. The error
count catches a noisy failure and the keeper check a refused one; a
silent hang inside a walk shows only as the age of a live execution.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

TREE_ROOT = Path(__file__).resolve().parents[1]
BEAMLINES = TREE_ROOT / "beamlines"
if str(BEAMLINES) not in sys.path:
    sys.path.append(str(BEAMLINES))

from descriptor import (  # noqa: E402
    DescriptorError,
    RunStep,
    load,
    load_operations,
    load_procedures,
)
from verify_hosts import (  # noqa: E402
    HOST_PROBE,
    SSH_TIMEOUT_SECONDS,
    UNITS_PROBE,
    HostReport,
    Unit,
    ask,
    check,
    host_uptime,
    units,
)

DEFAULT_PORT = 8809
DEFAULT_BOOK = BEAMLINES / "hosts.toml"
DEFAULT_SEEN = Path.home() / ".cora" / "fleet-seen.json"

HOST_INTERVAL_SECONDS = 600.0
"""How often the hosts are asked when nobody presses the button.

Ten minutes, because a probe is an ssh login on a machine that may be
writing a scan, and a bare login there has been measured at most of a
minute under that load. Service state changes rarely, and the button on
the page asks at once.
"""

HOP_TIMEOUT_SECONDS = 2 * SSH_TIMEOUT_SECONDS
"""A hop is two logins, and the second is made from a host that may be busy."""

KEEPER_INTERVAL_SECONDS = 30.0
KEEPER_TIMEOUT_SECONDS = 20.0

LISTING_LIMIT = 100
"""The largest page the keeper's listings accept, and the window shown.

The newest hundred executions at a beamline is a shift or a week depending
on the beamline, which is enough to see what is live and what has been
happening. Older work is in the record.
"""

DEFAULT_STALE_HOURS = 6.0
ERROR_FLOOD = 10
"""Errors in ten minutes past which a running conductor reads as degraded.

A conductor retrying a keeper that refuses it logs one every five seconds,
which is a hundred and twenty in ten minutes, and a healthy one logs none.
Ten sits far from both.
"""

LIVE = ("Dispatched", "Claimed", "Running")
SETTLED_WELL = ("Done",)
SETTLED_BADLY = ("Broken", "Refused")
RANK = {"ok": 0, "unknown": 1, "attention": 2, "fault": 3}
CONDUCTOR_UNIT = "cora-conductor.service"
PAGE_POLL_SECONDS = 5
OBSERVED = ("healthy", "degraded", "down", "off")
"""The health words that mean a component was read, whatever it said."""

KINDS: dict[str, str] = {
    "cora-conductor": "Conductor",
    "cora-reporter": "Reporter",
    "cora-motor-sim": "Simulated motors",
    "cora-tomoscan-sim": "Simulated TomoScan",
    "cora-keeper-ids": "Keeper id records",
    "cora-citation-ioc": "Citation records",
    "cora-watcher": "Watcher",
    "cora-keeper": "Keeper",
    "cora-keeper-postgres": "Database",
    "cora-keeper-jwks": "Key server",
    "cora-thinker": "Thinker",
    "cora-turner": "Turner",
}
"""What the page calls each unit the tree ships, keyed by the stem its template installs.

Named for what a visitor would call it rather than what it is built from,
since the page is shown to people who never read a unit file. Checked
against the unit templates by a test in the tree's tier, so a unit renamed
there fails here rather than showing under its file name.
"""

DESCRIPTIONS: dict[str, str] = {
    "cora-conductor": "Runs procedures at the beamline",
    "cora-reporter": "Files what each scan produced",
    "cora-motor-sim": "Motors to drive without moving hardware",
    "cora-tomoscan-sim": "A scan server to drive without starting a scan",
    "cora-keeper-ids": "Publishes the keeper's ids beside the scan server",
    "cora-citation-ioc": "Publishes citations beside the scan server",
    "cora-watcher": "Finishes moves and processing runs",
    "cora-keeper": "The record every part reads and writes",
    "cora-keeper-postgres": "Where the keeper holds its record",
    "cora-keeper-jwks": "Checks each client's credential",
    "cora-thinker": "An agent that answers questions about runs",
    "cora-turner": "An agent that turns pursuits",
}
"""One line on what each unit does, in the same words a visitor would use."""

PACKAGES: dict[str, tuple[str, str]] = {
    "cora-conductor": ("conductor", "main"),
    "cora-reporter": ("reporter", "main"),
    "cora-keeper": ("keeper", "main"),
    "cora-thinker": ("thinker", "main"),
    "cora-turner": ("conductor", "helper"),
    "cora-citation-ioc": ("conductor", "helper"),
    "cora-motor-sim": ("conductor", "testing"),
    "cora-tomoscan-sim": ("conductor", "testing"),
    "cora-watcher": ("reporter", "helper"),
    "cora-keeper-postgres": ("keeper", "helper"),
    "cora-keeper-jwks": ("keeper", "helper"),
    "cora-keeper-ids": ("beamlines", "helper"),
}
"""Which package ships each unit, and whether the unit is that package itself.

The package is the directory its template ships from, one of the four apps
or the facility's own for the one unit no app owns, so a test holds this
to the tree. A helper runs beside a package and does one job for it; a
testing unit is a software copy of a beamline's hardware, there so a
procedure can run without moving anything. The page leads with the four
packages and keeps the rest on a quieter line until one is in trouble.
"""

EVERY_BEAMLINE = ("cora-conductor", "cora-reporter")
"""Expected at every beamline, where the docs place a conductor and a reporter."""

ON_THE_CENTRAL_HOST = (
    "cora-keeper",
    "cora-keeper-postgres",
    "cora-keeper-jwks",
    "cora-thinker",
    "cora-turner",
)
"""Expected on the central host.

The keeper beside its database and the key server its tokens are checked
against, the thinker the docs place beside it, and the turner, whose
installer says there is one copy and it is central.
"""

FIXED_SEAMS: dict[str, list[list[str]]] = {
    "cora-motor-sim": [["Serves", "simulated motors a conductor drives without moving one"]],
    "cora-tomoscan-sim": [["Serves", "a simulated TomoScan a conductor scans with safely"]],
    "cora-keeper-ids": [["Serves", "two keeper id records beside an acquisition server"]],
    "cora-citation-ioc": [["Serves", "citation records beside a server that lacks them"]],
    "cora-watcher": [["Finishes", "moves and processing runs a driver stopped awaiting"]],
    "cora-keeper": [["Store", "Postgres, on loopback"], ["Tokens", "checked against the JWKS"]],
    "cora-keeper-postgres": [["Holds", "the event log"]],
    "cora-keeper-jwks": [["Serves", "the public keys tokens are checked against"]],
    "cora-turner": [["Turns", "pursuits, each naming its own beamline"]],
}

LANES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("tomography_scan",), "collect", "Collect"),
    (("process",), "process", "Process"),
    (("move",), "move", "Move"),
)
"""The data path in the order work moves along it, by the operations each leg runs.

Keyed by operation name, which is what `routines` on a dispatch carries,
and checked against the operation register by a test in the tree's tier.
A lane is a leg of the path rather than an operation, so it may run more
than one, which is how an operation replacing another shares its lane
while procedures still name both. Move goes whichever way its route says, between places a conductor
names, so one lane covers the trip out, the trip home and any hop
between; drawing each beamline's routes is a change of its own.
"""

_UNIT_NAME = re.compile(r"^cora-[A-Za-z0-9@._-]+\.service$")
"""What a unit name must look like before it is written into a script.

The names come back from a host's own listing and are interpolated into a
second script run on another host, so anything else is dropped rather
than quoted.
"""

_ENVIRON_READ = (
    'tr "\\0" "\\n" < /proc/$(systemctl --user show -p MainPID --value cora-conductor)'
    '/environ | grep -E "^(EPICS_CA|CORA_(MOVE|COMPUTE))_"'
)


@dataclass(frozen=True)
class Target:
    """Where a beamline's conductor, or the central host, is asked."""

    host: str
    account: str = ""
    routable: tuple[str, ...] = ()
    private: tuple[str, ...] = ()

    @property
    def ssh(self) -> str:
        return self.on(self.host)

    def on(self, host: str) -> str:
        """The same account on another host in the same beamline."""
        return f"{self.account}@{host}" if self.account else host

    @classmethod
    def parse(cls, target: str) -> Target:
        account, _, host = target.rpartition("@")
        return cls(host=host, account=account)


@dataclass
class Book:
    """Which machine to ask for each beamline, and why a beamline has none."""

    targets: dict[str, Target] = field(default_factory=dict[str, Target])
    missing: dict[str, str] = field(default_factory=dict[str, str])
    central: Target | None = None
    central_host: str = ""


@dataclass
class HostAnswer:
    """One beamline's probe, and its units asked on the hosts they are pinned to.

    `elsewhere` maps a unit to the host it was asked on, what that host
    said, and why it said nothing when it did not answer.
    """

    report: HostReport
    asked_at: float
    seconds: float
    elsewhere: dict[str, tuple[str, str, str]] = field(
        default_factory=dict[str, tuple[str, str, str]]
    )
    pinned: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    """Each other host that was asked: whether it answered, its uptime, and ssh's reason."""


@dataclass
class CentralAnswer:
    """The central host's units, when the address book names an account there."""

    asked_at: float
    seconds: float
    units: list[Unit] = field(default_factory=list[Unit])
    unreachable: str | None = None
    uptime: int | None = None


@dataclass
class KeeperAnswer:
    """What the keeper said on one round, per beamline where it differs."""

    asked_at: float
    url: str
    version: str | None = None
    ready: str | None = None
    error: str | None = None
    executions: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict[str, list[dict[str, Any]]]
    )
    unfiled: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict[str, list[dict[str, Any]]]
    )
    failures: dict[str, str] = field(default_factory=dict[str, str])


def read_book(
    path: Path | None,
    slugs: list[str],
    overrides: dict[str, str],
    central: str | None = None,
) -> Book:
    """The targets for every beamline, from the address book and the flags.

    A beamline with no `conductor` key falls back to its routable host only
    where it has exactly one, which is the facility's pattern. The one
    beamline that breaks the pattern runs its conductor on a private host,
    so the fallback refuses to choose among private hosts rather than
    asking whichever is listed first.
    """
    book = Book()
    settings: dict[str, Any] = {}
    if path is not None and path.is_file():
        settings = tomllib.loads(path.read_text(encoding="utf-8"))
    tables: dict[str, Any] = settings.get("beamline") or {}
    for slug in slugs:
        table: dict[str, Any] = tables.get(slug) or {}
        routable = tuple(str(host) for host in table.get("routable", ()))
        private = tuple(str(host) for host in table.get("private", ()))
        account = str(table.get("account", ""))
        if slug in overrides:
            given = Target.parse(overrides[slug])
            book.targets[slug] = Target(given.host, given.account or account, routable, private)
            continue
        host = str(table.get("conductor", "")) or (routable[0] if len(routable) == 1 else "")
        if host:
            book.targets[slug] = Target(host, account, routable, private)
        elif not settings:
            book.missing[slug] = (
                f"no address book at {path}, so no host to ask. Pass --book, or --host SLUG=TARGET"
            )
        elif not table:
            book.missing[slug] = "the address book has no table for this beamline"
        else:
            book.missing[slug] = (
                "the address book names no conductor host here and there is no single "
                "routable host to fall back on. Add conductor = ... to its table"
            )
    central_table: dict[str, Any] = settings.get("central") or {}
    book.central_host = str(central_table.get("host", ""))
    if central:
        book.central = Target.parse(central)
        book.central_host = book.central_host or book.central.host
    elif central_table.get("host") and central_table.get("account"):
        book.central = Target(str(central_table["host"]), str(central_table["account"]))
    return book


def read_tree(root: Path) -> dict[str, Any]:
    """The registers, summarised to what the page shows.

    `away` is every operation some register runs in a step that drives no
    device: work done at another facility, which is what this page calls
    data movement. It is read from the registers rather than listed here,
    so an operation added there is classified without touching this file.
    """
    operations = [entry.name for entry in load_operations(root / "operations.toml").operations]
    away: set[str] = set()
    beamlines: dict[str, Any] = {}
    for directory in sorted(path for path in root.iterdir() if (path / "devices.toml").is_file()):
        register = load(directory / "devices.toml")
        groups = Counter(device.group for device in register.devices if device.group)
        procedures: list[dict[str, Any]] = []
        if (directory / "procedures.toml").is_file():
            for procedure in load_procedures(directory / "procedures.toml").procedures:
                runs = [step for step in procedure.steps if isinstance(step, RunStep)]
                away.update(step.operation for step in runs if step.drives_no_device)
                procedures.append(
                    {
                        "name": procedure.name,
                        "confirmed": procedure.confirmed,
                        "operations": sorted({step.operation for step in runs}),
                        "sets": len(procedure.steps) - len(runs),
                    }
                )
        adapters: dict[str, str] = {}
        if (directory / "adapters.toml").is_file():
            raw = tomllib.loads((directory / "adapters.toml").read_text(encoding="utf-8"))
            for section, slots in raw.items():
                if isinstance(slots, dict):
                    for key, value in cast("dict[str, Any]", slots).items():
                        adapters[f"{section}.{key}"] = str(value)
        beamlines[directory.name] = {
            "devices": {
                "total": len(register.devices),
                "confirmed": sum(1 for device in register.devices if device.confirmed),
                "groups": sorted(groups.items()),
            },
            "procedures": procedures,
            "adapters": adapters,
        }
    facility: dict[str, Any] = {}
    if (root / "facility.toml").is_file():
        facility = tomllib.loads((root / "facility.toml").read_text(encoding="utf-8"))
    return {
        "revision": _revision(root.parent),
        "behind_main": _behind_main(root.parent),
        "operations": operations,
        "away": sorted(away),
        "facility": facility,
        "beamlines": beamlines,
    }


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def _revision(root: Path) -> str | None:
    return _git(root, "rev-parse", "HEAD") or None


def _behind_main(root: Path) -> int | None:
    """How many commits on main this checkout does not hold, or None without a main."""
    count = _git(root, "rev-list", "--count", "HEAD..main")
    return int(count) if count.isdigit() else None


def distance_to_head(root: Path, revision: str) -> int | None:
    """How many commits a deployed revision is behind this checkout, or None if not held."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", revision):
        return None
    if subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", revision, "HEAD"],
        capture_output=True,
        check=False,
    ).returncode:
        return None
    count = _git(root, "rev-list", "--count", f"{revision}..HEAD")
    return int(count) if count.isdigit() else None


def _short(host: str) -> str:
    return host.split("@")[-1].split(".")[0]


def role(host: str, target: Target | None, central_host: str) -> str:
    """What a host is for, said without its name, which is a facility coordinate."""
    short = _short(host)
    if not short:
        return "unread host"
    if central_host and short == _short(central_host):
        return "central host"
    if target is not None and short == _short(target.host):
        return "conductor host"
    return "beamline host"


def place(host: str, target: Target | None, central_host: str) -> str:
    """Where a host sits, said as its role and then its name."""
    short = _short(host)
    if not short:
        return "where it was pinned could not be read"
    return f"the {role(host, target, central_host)}, {short}"


def pinned_elsewhere(here: str, found: list[Unit]) -> dict[str, list[str]]:
    """The units whose `ConditionHost` is not the host that was probed, by host."""
    by_host: dict[str, list[str]] = {}
    for unit in found:
        moved = unit.condition and _short(unit.condition) != _short(here)
        if moved and _UNIT_NAME.match(unit.name):
            by_host.setdefault(unit.condition, []).append(unit.name)
    return by_host


def hop(target: Target) -> list[str]:
    """The ssh options that reach another host of a beamline through its conductor host."""
    return ["-J", target.ssh]


def ask_elsewhere(
    target: Target, found: list[Unit], ssh_opts: list[str]
) -> tuple[dict[str, tuple[str, str, str]], dict[str, dict[str, Any]]]:
    """Ask each pinned unit's own host whether it is running there, and the host its uptime.

    Through the conductor's host, which is on the beamline's own network, so
    a host that answers is also a host the conductor's host can reach. A
    host that does not answer leaves its units `unasked` with ssh's own
    reason, which the fold reads as unknown. Writing `inactive` for them
    would report a simulator down because the IOC host was busy.
    """
    answers: dict[str, tuple[str, str, str]] = {}
    hosts: dict[str, dict[str, Any]] = {}
    for host, names in pinned_elsewhere(target.host, found).items():
        script = (
            "printf 'uptime|%s\\n' \"$(cut -d' ' -f1 /proc/uptime 2>/dev/null)\"\n"
            "for u in " + " ".join(names) + "; do\n"
            '  printf "%s|%s\\n" "$u" "$(systemctl --user is-active "$u" 2>/dev/null)"\n'
            "done\n"
        )
        code, out = ask(
            target.on(host), script, [*ssh_opts, *hop(target)], timeout=HOP_TIMEOUT_SECONDS
        )
        said: dict[str, str] = {}
        uptime = None
        if code == 0:
            for line in out.splitlines():
                name, separator, state = line.partition("|")
                if not separator:
                    continue
                if name == "uptime":
                    whole = state.strip().split(".")[0]
                    uptime = int(whole) if whole.isdigit() else None
                else:
                    said[name.strip()] = state.strip()
        reason = "" if code == 0 else (out.strip().splitlines() or ["no answer"])[-1]
        hosts[host] = {"reached": code == 0, "uptime": uptime, "said": reason}
        for name in names:
            answers[name] = (host, said.get(name) or "unasked", reason)
    return answers, hosts


def ask_beamline(slug: str, target: Target, ssh_opts: list[str]) -> HostAnswer:
    started = time.time()
    report = check(slug, target.ssh, BEAMLINES, ssh_opts, None)
    elsewhere: dict[str, tuple[str, str, str]] = {}
    pinned: dict[str, dict[str, Any]] = {}
    if not report.unreachable:
        elsewhere, pinned = ask_elsewhere(target, report.units, ssh_opts)
    return HostAnswer(report, started, time.time() - started, elsewhere, pinned)


def ask_central(target: Target, ssh_opts: list[str]) -> CentralAnswer:
    started = time.time()
    code, out = ask(target.ssh, HOST_PROBE + UNITS_PROBE, ssh_opts)
    if code != 0 or "== units" not in out:
        reason = out.strip().splitlines()[-1] if out.strip() else "no answer"
        return CentralAnswer(started, time.time() - started, unreachable=reason)
    return CentralAnswer(started, time.time() - started, units=units(out), uptime=host_uptime(out))


class KeeperError(Exception):
    """A keeper call that did not return a body this page can read."""


class Keeper:
    """The few GETs this page makes, with the token and the CA it was given."""

    def __init__(self, url: str, token: str | None, context: ssl.SSLContext) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.context = context

    def get(self, path: str, **query: str) -> Any:
        encoded = urllib.parse.urlencode(query)
        request = urllib.request.Request(f"{self.url}{path}{'?' + encoded if encoded else ''}")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(
                request, timeout=KEEPER_TIMEOUT_SECONDS, context=self.context
            ) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:200]
            raise KeeperError(f"{error.code} from {path}: {body or error.reason}") from error
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as error:
            raise KeeperError(f"{path} did not answer: {error}") from error


def ask_keeper(keeper: Keeper, slugs: list[str]) -> KeeperAnswer:
    answer = KeeperAnswer(asked_at=time.time(), url=keeper.url)
    try:
        answer.version = str(keeper.get("/health").get("version", ""))
    except KeeperError as error:
        answer.error = str(error)
        return answer
    try:
        answer.ready = str(keeper.get("/readyz").get("status", ""))
    except KeeperError as error:
        answer.ready = str(error)
    for slug in slugs:
        try:
            limit = str(LISTING_LIMIT)
            answer.executions[slug] = keeper.get("/executions", beamline=slug, limit=limit).get(
                "items", []
            )
            answer.unfiled[slug] = keeper.get(
                "/steps/without-datasets", beamline=slug, limit=limit
            ).get("items", [])
        except KeeperError as error:
            answer.failures[slug] = str(error)
    return answer


def _epoch(stamp: str) -> float:
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def age(seconds: float) -> str:
    """A duration a person reads at a glance, coarse on purpose."""
    if seconds < 60:
        return "under a minute"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{int(seconds // 86400)} days"


def cause(tag: str, text: str, fix: str = "") -> dict[str, str]:
    """A reason with a short tag for a row, a sentence for a reader, and the source to fix."""
    return {"tag": tag, "text": text, "fix": fix}


def why_unasked(said: str) -> dict[str, str]:
    """Why a host could not be asked, sorted into the few things a person does about it."""
    lowered = said.lower()
    if "permission denied" in lowered:
        return cause(
            "login refused",
            f"The ssh login was refused ({said}). The page logs in without a prompt, "
            "so the key has to be in the agent.",
            "hosts",
        )
    if "could not resolve" in lowered or "not known" in lowered or "nodename nor" in lowered:
        return cause("name does not resolve", f"The host's name did not resolve: {said}.", "book")
    if "timed out" in lowered or "timeout" in lowered:
        return cause(
            "did not answer in time",
            f"The host did not answer a login in time ({said}). A host writing a scan "
            "can take most of a minute, so this is not the same as down.",
        )
    if "connection refused" in lowered:
        return cause("refused the login", f"The host refused the ssh connection: {said}.")
    if "no route" in lowered:
        return cause("no route", f"There is no route to the host from here: {said}.")
    return cause("could not be asked", said or "The host gave no answer.")


def from_systemd(enabled: str, active: str, said: str = "") -> tuple[str, dict[str, str]]:
    """A unit's health from the two words systemd gives, judged where it runs."""
    armed = enabled.startswith("enabled") or enabled in ("static", "linked")
    if active == "active":
        if armed:
            return "healthy", cause("active", "Active on the host it is pinned to, asked there.")
        return "degraded", cause(
            "running, not armed",
            f"Running and {enabled or 'not enabled'}, so a reboot of its host does not "
            "bring it back.",
        )
    if active == "unasked":
        return "unknown", why_unasked(said)
    if active in ("activating", "deactivating", "reloading"):
        return "degraded", cause(active, f"{active.capitalize()} when it was asked.")
    if armed:
        return "down", cause(
            f"enabled, {active or 'silent'}",
            f"Enabled and {active or 'not answering'} on the host it is pinned to.",
        )
    return "off", cause(
        "disabled, stopped",
        f"{(enabled or 'not enabled').capitalize()} and not running, which is a choice "
        "rather than a fault.",
    )


def _kind(name: str) -> str:
    """The template a unit was installed from: its stem, or the longest one it extends."""
    stem = name.removesuffix(".service")
    if stem in KINDS:
        return stem
    extended = [known for known in KINDS if stem.startswith(known + "-")]
    return max(extended, key=len) if extended else stem


def _label(name: str) -> str:
    stem = name.removesuffix(".service")
    kind = _kind(name)
    if kind not in KINDS:
        return stem
    extra = stem[len(kind) + 1 :]
    return f"{KINDS[kind]}, {extra}" if extra else KINDS[kind]


def merged(
    seen: dict[str, dict[str, Any]], observed: list[dict[str, Any]], now: float
) -> dict[str, dict[str, Any]]:
    """The remembered inventory with this round's readings folded in.

    Keyed by owner and unit, so a unit that moves between hosts keeps one
    entry. Only units actually read are written; a unit that went unasked
    keeps the last reading it had, which is the point of remembering.
    """
    out = {key: dict(entry) for key, entry in seen.items()}
    for entry in observed:
        key = f"{entry['owner']}/{entry['name']}"
        out[key] = {**entry, "at": now}
    return out


def observed_from(slug: str, answer: HostAnswer, book: Book) -> list[dict[str, Any]]:
    """The units one probe actually read, ready to remember."""
    if answer.report.unreachable:
        return []
    found: list[dict[str, Any]] = []
    for unit in answer.report.units:
        host, active, _ = answer.elsewhere.get(
            unit.name, (unit.condition or answer.report.target, unit.active, "")
        )
        if active == "unasked":
            continue
        owner = "central" if _is_central(unit.condition, book) else slug
        found.append(
            {
                "owner": owner,
                "name": unit.name,
                "host": host,
                "enabled": unit.enabled,
                "active": active,
            }
        )
    return found


def _is_central(host: str, book: Book) -> bool:
    return bool(book.central_host and host and _short(host) == _short(book.central_host))


def _seams(
    kind: str, registers: dict[str, Any], report: HostReport | None, facility: dict[str, Any]
) -> list[list[str]]:
    adapters: dict[str, str] = registers.get("adapters", {}) if registers else {}
    if kind == "cora-conductor":
        seams = [
            ["Running", adapters.get("driving.scan_engine", "unsurveyed")],
            ["Adjusting", adapters.get("driving.control_system", "unsurveyed")],
        ]
        if report is not None:
            for engine in report.engines:
                where = engine.prefix or engine.profile or "unnamed"
                seams.append([", ".join(engine.routines) or "no routine", where])
            if report.writable:
                seams.append(["May write", ", ".join(report.writable)])
        return seams
    if kind == "cora-reporter":
        return [
            ["Delivering", adapters.get("recording.deliveries", "unsurveyed")],
            ["Describing", adapters.get("recording.data_format", "unsurveyed")],
            ["Locating", adapters.get("recording.store", "unsurveyed")],
        ]
    if kind == "cora-thinker":
        thinking: dict[str, Any] = facility.get("thinking") or {}
        return [["Inference", str(thinking.get("inference", "unset"))]]
    return [list(pair) for pair in FIXED_SEAMS.get(kind, [])]


def _sync(
    kind: str, report: HostReport | None, head: str | None, distance: dict[str, int | None]
) -> tuple[str, str]:
    app = {"cora-conductor": "conductor", "cora-reporter": "reporter"}.get(kind)
    if app is None or report is None:
        return "syncunknown", "Not versioned with the tree."
    revision = report.revisions.get(app, "unnamed")
    if revision == "unnamed":
        return "syncunknown", "Its install left no REVISION, so what it runs cannot be named."
    if head and head.startswith(revision[:7]):
        return "insync", f"At {revision[:7]}, the revision this page reads."
    behind = distance.get(revision)
    if behind is None:
        return "drifted", f"At {revision[:7]}, which this checkout does not hold."
    return "drifted", f"At {revision[:7]}, {behind} commits behind the revision this page reads."


def _part(
    name: str,
    *,
    where: str,
    host: str,
    health: str,
    why: dict[str, str],
    seams: list[list[str]],
    sync: tuple[str, str] = ("syncunknown", "Not read."),
    found: bool = False,
    external: bool = False,
) -> dict[str, Any]:
    return {
        "id": name.removesuffix(".service"),
        "name": _label(name) if name.startswith("cora-") else name,
        "unit": name if name.startswith("cora-") else "",
        "kind": _kind(name),
        "description": DESCRIPTIONS.get(_kind(name), ""),
        "package": PACKAGES.get(_kind(name), ("", "external"))[0],
        "tier": PACKAGES.get(_kind(name), ("", "external"))[1],
        "where": where,
        "host": host,
        "hostname": _short(host) if host else "",
        "role": "",
        "health": health,
        "cause": why,
        "sync": sync[0],
        "sync_why": sync[1],
        "seams": seams,
        "found": found,
        "external": external,
    }


def _hosts(
    parts: list[dict[str, Any]],
    target: Target | None,
    report: HostReport | None,
    answer: HostAnswer | None,
    failed: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """The hosts a beamline's components run on, each with whether it answered and its uptime.

    The conductor's host answered when its probe did. Every other host was
    asked through the conductor's host, so one that answered is also one the
    conductor's host can reach, which is the network fact this page can
    measure without touching an IOC.
    """
    hosts: dict[str, dict[str, Any]] = {}

    routable: set[str] = {_short(host) for host in target.routable} if target else set()
    private: set[str] = {_short(host) for host in target.private} if target else set()

    def entry(name: str, host_role: str) -> dict[str, Any]:
        network = "routable" if name in routable else "private" if name in private else "unknown"
        return hosts.setdefault(
            name,
            {
                "name": name,
                "role": host_role,
                "network": network,
                "reached": None,
                "uptime": None,
                "why": "",
                "parts": [],
            },
        )

    conductor = _short(target.host) if target is not None else ""
    if conductor:
        found = entry(conductor, "conductor host")
        if report is not None:
            found["reached"], found["uptime"] = True, report.uptime
        elif failed is not None:
            found["reached"], found["why"] = False, failed["tag"]
    for part in parts:
        if not part["external"] and part["hostname"]:
            entry(part["hostname"], part["role"])["parts"].append(part["id"])
    for host, said in (answer.pinned if answer is not None else {}).items():
        found = hosts.get(_short(host))
        if found is None:
            continue
        found["reached"] = bool(said.get("reached"))
        found["uptime"] = said.get("uptime")
        found["why"] = "" if said.get("reached") else why_unasked(str(said.get("said", "")))["tag"]
    return sorted(hosts.values(), key=lambda found: (found["name"] != conductor, found["name"]))


def _keeper_link(report: HostReport | None) -> dict[str, str]:
    """Whether a beamline's conductor host reaches the keeper, asked the way the conductor asks."""
    if report is None or report.keeper is None:
        return {"state": "unknown", "text": "Not asked from this beamline."}
    reach = report.keeper
    if reach.answers:
        return {"state": "ok", "text": "The keeper answers the conductor host."}
    state = "refused" if "refuses" in reach.reason else "unreachable"
    return {"state": state, "text": f"The keeper {reach.reason} from the conductor host."}


def _version(
    report: HostReport | None, head: str | None, distance: dict[str, int | None]
) -> dict[str, Any]:
    """The conductor's deployed revision, and how far behind the revision this page reads."""
    revision = report.revisions.get("conductor", "") if report is not None else ""
    if not revision or revision == "unnamed":
        return {"state": "syncunknown", "revision": "", "behind": None}
    if head and head.startswith(revision[:7]):
        return {"state": "insync", "revision": revision[:7], "behind": 0}
    return {"state": "drifted", "revision": revision[:7], "behind": distance.get(revision)}


def _engine(report: HostReport | None) -> dict[str, str]:
    """What a beamline's scan engine drives: the station's own server, or a simulator.

    A simulator is recognised by the prefix its own unit serves and never by
    how a prefix is spelled, because no installer makes a simulator's prefix
    look like one.
    """
    if report is None:
        return {"kind": "unknown", "prefix": ""}
    prefix = next((engine.prefix for engine in report.engines if engine.prefix), "")
    if not prefix:
        return {"kind": "none", "prefix": ""}
    if report.simulated and prefix == report.simulated:
        return {"kind": "simulated", "prefix": prefix}
    return {"kind": "station", "prefix": prefix}


def _judge_keeper(
    keeper: KeeperAnswer | None,
    vantages: list[tuple[str, Any]],
    unit_active: str | None,
) -> tuple[str, dict[str, str]]:
    """Whether the keeper is up, from every place that asked it.

    The page's own read and each conductor host's are separate vantage
    points. A keeper the page cannot reach may be one every beamline
    reaches, and a keeper refused from every conductor host is down even
    when the page has no route to it at all.
    """
    answering = [slug for slug, reach in vantages if reach.answers]
    refusing = [slug for slug, reach in vantages if not reach.answers]
    if keeper is not None and keeper.error is None:
        if keeper.ready == "ready":
            return "healthy", cause("answers and is ready", "The keeper answers and is ready.")
        return "down", cause(
            "answers, not ready", f"The keeper answers and is not ready: {keeper.ready}.", "keeper"
        )
    if answering:
        return "healthy", cause(
            "answers its conductors", f"The keeper answers from {', '.join(answering)}."
        )
    if unit_active is not None and unit_active not in ("active", "unasked"):
        refused = f" It is refused from {', '.join(refusing)}." if refusing else ""
        return "down", cause(
            "not running",
            f"Its unit is {unit_active} on the central host.{refused}",
            "keeper",
        )
    if refusing and len(refusing) == len(vantages):
        return "down", cause(
            "refused everywhere",
            f"Every conductor host that asked was refused: {', '.join(refusing)}.",
            "keeper",
        )
    if keeper is not None and keeper.error:
        return "unknown", cause("not read from here", f"Not readable from here: {keeper.error}.")
    return "unknown", cause(
        "not asked", "No keeper address was given here, and no conductor host reported."
    )


def _record(
    slug: str,
    keeper: KeeperAnswer | None,
    routines_here: set[str] | None,
    away: set[str],
    now: float,
    stale_hours: float,
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    """What the keeper holds for one beamline, and what in it needs a person."""
    if keeper is None or keeper.error is not None:
        return {"read": False}
    if slug in keeper.failures:
        findings.append(
            {
                "level": "unknown",
                "source": "keeper",
                "text": f"the keeper would not list this beamline: {keeper.failures[slug]}",
            }
        )
        return {"read": False}
    items = keeper.executions.get(slug, [])
    live: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for item in items:
        listed: list[Any] = item.get("routines") or []
        routines = [str(routine) for routine in listed]
        stamp = item.get("updated_at") or item.get("created_at")
        at = _epoch(str(stamp)) if stamp else now
        since = now - at
        row = {
            "procedure": item.get("procedure_name", ""),
            "status": item.get("status", ""),
            "steps": item.get("step_count", 0),
            "reported": item.get("reported_count", 0),
            "routines": routines,
            "at": at,
        }
        rows.append(row)
        if row["status"] not in LIVE:
            continue
        live.append(row)
        waiting = sorted(set(routines) - routines_here) if routines_here is not None else []
        if row["status"] == "Dispatched" and waiting:
            findings.append(
                {
                    "level": "fault",
                    "source": "record",
                    "text": f"{row['procedure']!r} has waited {age(since)} at Dispatched for "
                    f"{waiting}, which no engine at this beamline runs, so no conductor "
                    "will take it up",
                }
            )
        elif since > stale_hours * 3600:
            findings.append(
                {
                    "level": "attention",
                    "source": "record",
                    "text": f"{row['procedure']!r} has been {row['status']} for {age(since)} "
                    f"with {row['reported']} of {row['steps']} steps reported",
                }
            )
    unfiled = keeper.unfiled.get(slug, [])
    if unfiled:
        many = "at least " if len(unfiled) >= LISTING_LIMIT else ""
        findings.append(
            {
                "level": "attention",
                "source": "record",
                "text": f"{many}{len(unfiled)} run(s) reported with no dataset filed against them",
            }
        )
    return {
        "read": True,
        "counts": dict(Counter(str(item.get("status", "")) for item in items)),
        "window": len(items),
        "live": live,
        "moving": [row for row in rows if set(row["routines"]) & away][:8],
        "rows": rows,
        "unfiled": len(unfiled),
    }


def _legs(
    registers: dict[str, Any],
    routines_here: set[str] | None,
    record: dict[str, Any],
    keeper_down: bool,
    now: float,
) -> dict[str, dict[str, Any]]:
    """Each leg of the data path at one beamline, from register, engine and record."""
    legs: dict[str, dict[str, Any]] = {}
    procedures: list[dict[str, Any]] = registers.get("procedures", [])
    for operations, lane, _ in LANES:
        runs = set(operations)
        running = [p for p in procedures if runs & set(p["operations"])]
        confirmed = any(p["confirmed"] for p in running)
        engine = None if routines_here is None else bool(runs & routines_here)
        last = None
        if record.get("read"):
            last = next((row for row in record["rows"] if runs & set(row["routines"])), None)
        if not running and engine is not True:
            state, note = "absent", "No procedure here runs it and no engine is set for it."
        elif keeper_down:
            ready = "confirmed" if confirmed else "registered"
            state = "blocked"
            note = f"Nothing can be dispatched while the keeper is down. It is {ready} here."
        elif last is not None and last["status"] in SETTLED_WELL:
            state, note = "proven", f"Last done {age(now - last['at'])} ago."
        elif last is not None and last["status"] in SETTLED_BADLY:
            state, note = "failing", f"Last run {last['status']} {age(now - last['at'])} ago."
        elif last is not None:
            state, note = "running", f"{last['status']} for {age(now - last['at'])}."
        elif engine is False:
            state = "blocked"
            note = "Registered here, and no engine at this beamline runs it."
        elif confirmed:
            state = "confirmed"
            unread = "" if record.get("read") else " The record was not read."
            note = (
                "A confirmed procedure runs it"
                + (", and the conductor has an engine for it." if engine else ".")
                + unread
            )
        else:
            state, note = "declared", "Registered, and no procedure running it is confirmed."
        legs[lane] = {"state": state, "op": operations[0], "ops": list(operations), "note": note}
    return legs


def _beamline(
    slug: str,
    tree: dict[str, Any],
    book: Book,
    answer: HostAnswer | None,
    keeper: KeeperAnswer | None,
    seen: dict[str, dict[str, Any]],
    distance: dict[str, int | None],
    keeper_down: bool,
    now: float,
    stale_hours: float,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """One beamline's card, and what its host and registers disagree about."""
    registers = tree["beamlines"][slug]
    target = book.targets.get(slug)
    report = answer.report if answer is not None else None
    reached = report is not None and not report.unreachable
    head = tree["revision"]
    facility: dict[str, Any] = tree.get("facility") or {}
    parts: list[dict[str, Any]] = []
    disagreements: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []

    if target is None:
        failed = cause("host not named", book.missing.get(slug, "No host to ask."), "book")
    elif answer is None:
        failed = cause("not asked yet", "The hosts have not been asked yet.")
    elif report is not None and report.unreachable:
        failed = why_unasked(report.unreachable)
    else:
        failed = None

    listed: set[str] = set()
    if reached and report is not None and answer is not None:
        for unit in report.units:
            if _is_central(unit.condition, book):
                continue
            listed.add(unit.name.removesuffix(".service"))
            host, active, said = answer.elsewhere.get(
                unit.name, (unit.condition or report.target, unit.active, "")
            )
            health, why = from_systemd(unit.enabled, active, said)
            kind = _kind(unit.name)
            if kind == "cora-conductor" and health == "healthy":
                health, why = _conductor_health(report)
            elif kind in ("cora-reporter", "cora-watcher") and health == "healthy" and keeper_down:
                health, why = (
                    "degraded",
                    cause(
                        "running, nowhere to file",
                        "systemd says active, and the keeper it files to is down, so nothing "
                        "it reports now can be recorded.",
                        "keeper",
                    ),
                )
            parts.append(
                _part(
                    unit.name,
                    where=place(host, target, book.central_host),
                    host=host,
                    health=health,
                    why=why,
                    seams=_seams(kind, registers, report, facility),
                    sync=_sync(kind, report, head, distance),
                    found=kind not in EVERY_BEAMLINE,
                )
            )

    for stem in EVERY_BEAMLINE:
        if stem in listed:
            continue
        name = stem + ".service"
        memory = seen.get(f"{slug}/{name}")
        if reached:
            if stem == "cora-conductor":
                health, why = (
                    "down",
                    cause(
                        "no conductor unit",
                        "The account holds no conductor unit, so nothing here takes work from "
                        "the keeper.",
                    ),
                )
            else:
                health, why = (
                    "notinstalled",
                    cause("not installed", "The account holds no unit for it."),
                )
        else:
            assert failed is not None
            health, why = "unknown", _remembered(failed, memory, now)
        host = str(memory["host"]) if memory else (target.host if target else "")
        parts.append(
            _part(
                name,
                where=place(host, target, book.central_host) if host else "not read",
                host=host,
                health=health,
                why=why,
                seams=_seams(stem, registers, report if reached else None, facility),
            )
        )
        listed.add(stem)

    for key, memory in sorted(seen.items()):
        owner, _, name = key.partition("/")
        stem = name.removesuffix(".service")
        if owner != slug or stem in listed:
            continue
        host = str(memory.get("host", ""))
        if reached:
            health = "notinstalled"
            why = cause(
                "gone",
                f"Seen {age(now - float(memory.get('at', now)))} ago, and no longer in the "
                "account.",
            )
            disagreements.append(
                {
                    "where": f"{slug}, {name}",
                    "text": f"Seen {age(now - float(memory.get('at', now)))} ago and gone "
                    "from the account now.",
                    "decide": "Whether it was removed on purpose.",
                }
            )
        else:
            assert failed is not None
            health, why = "unknown", _remembered(failed, memory, now)
        parts.append(
            _part(
                name,
                where=place(host, target, book.central_host) if host else "not read",
                host=host,
                health=health,
                why=why,
                seams=_seams(_kind(name), registers, None, facility),
                found=_kind(name) not in EVERY_BEAMLINE,
            )
        )
        listed.add(stem)

    parts.append(
        _part(
            "Beamline IOCs",
            where="the beamline's own hosts",
            host="",
            health="unmonitored",
            why=cause(
                "nothing reads a record",
                "No check asks an IOC whether it answers, so one that stopped looks the "
                "same as one that is idle.",
            ),
            seams=[["Owned by", "the beamline, not by CORA"]],
            external=True,
        )
    )
    order = {stem: index for index, stem in enumerate(KINDS)}
    parts.sort(
        key=lambda part: (part["external"], order.get(part["kind"], len(order)), part["name"])
    )
    for part in parts:
        part["role"] = role(part["host"], target, book.central_host) if part["host"] else ""

    routines_here = (
        {routine for engine in report.engines for routine in engine.routines}
        if reached and report is not None
        else None
    )
    away = set(tree["away"])
    record = _record(slug, keeper, routines_here, away, now, stale_hours, findings)
    legs = _legs(registers, routines_here, record, keeper_down, now)

    compute = None
    environ: dict[str, str] = {}
    if reached and report is not None:
        for problem in report.problems:
            if problem.startswith("the keeper this conductor"):
                continue
            disagreements.append(
                {"where": f"{slug}, its host against the registers", "text": problem, "decide": ""}
            )
        environ = {
            name: value for name, value in report.environ.items() if name.startswith("EPICS_")
        }
        values = {
            key: report.environ.get(f"CORA_COMPUTE_{key.upper()}", "")
            for key in ("endpoint", "project", "queue")
        }
        compute = values if any(values.values()) else None
        movers = sorted((routines_here or set()) & away)
        processing = [
            value for key, value in registers["adapters"].items() if key.startswith("processing.")
        ]
        if movers and processing and all(value == "none" for value in processing):
            disagreements.append(
                {
                    "where": f"beamlines/{slug}/adapters.toml",
                    "text": f"The conductor runs engines for {movers}, work done at another "
                    "facility, while every processing slot says none.",
                    "decide": "Whether those engines fill the processing slots.",
                }
            )

    facts: list[list[str]] = []
    if target is not None:
        facts.append(["Conductor runs on", place(target.host, target, book.central_host)])
    if reached and report is not None:
        if environ.get("EPICS_CA_AUTO_ADDR_LIST", "").upper() == "NO" and environ.get(
            "EPICS_CA_ADDR_LIST"
        ):
            facts.append(["Finds its records by", "an explicit address list"])
        elif environ.get("EPICS_CA_ADDR_LIST"):
            facts.append(["Finds its records by", "broadcast, and an address list"])
        else:
            facts.append(["Finds its records by", "the defaults it inherited"])
        if report.keeper is not None:
            facts.append(["Its keeper", f"{report.keeper.url}, which {report.keeper.reason}"])
        revisions = ", ".join(f"{app} {sha[:7]}" for app, sha in report.revisions.items())
        facts.append(["Revisions", revisions])
        if report.errors is not None:
            facts.append(["Conductor errors, last ten minutes", str(report.errors)])
    offsite = [
        {"op": leg["op"], "state": leg["state"], "lane": lane}
        for lane, leg in legs.items()
        if set(leg["ops"]) & away and leg["state"] != "absent"
    ]

    level = "ok"
    for item in findings:
        if RANK[item["level"]] > RANK[level]:
            level = item["level"]
    shown = report if reached else None
    card = {
        "slug": slug,
        "title": slug.upper(),
        "sector": _sector(slug)[0],
        "hosts": _hosts(parts, target, shown, answer, failed),
        "keeper_link": _keeper_link(shown),
        "engine": _engine(shown),
        "version": _version(shown, head, distance),
        "target": None if target is None else {"host": target.host, "account": target.account},
        "asked": None if answer is None else {"at": answer.asked_at, "seconds": answer.seconds},
        "reached": reached,
        "failed": failed,
        "facts": facts,
        "parts": parts,
        "legs": legs,
        "offsite": offsite,
        "compute": compute,
        "environ": environ,
        "record": record,
        "findings": findings,
        "level": level,
        "registers": registers,
        "commands": commands(slug, target, sorted({h for h, _, _ in answer.elsewhere.values()}))
        if target is not None and answer is not None
        else [],
    }
    return card, disagreements


def _conductor_health(report: HostReport) -> tuple[str, dict[str, str]]:
    """A running conductor's health, which systemd alone overstates."""
    reach = report.keeper
    if reach is not None and not reach.answers:
        brief = "refuses it" if "refuses" in reach.reason else "unreachable"
        return "degraded", cause(
            f"running, keeper {brief}",
            f"systemd says active, and from its host the keeper it is configured with "
            f"{reach.reason}, so it can take no work.",
            "keeper",
        )
    if report.errors is not None and report.errors >= ERROR_FLOOD:
        last = f" The last: {report.last_error}" if report.last_error else ""
        return "degraded", cause(
            "running, logging errors",
            f"systemd says active, and it logged {report.errors} errors in the last ten "
            f"minutes.{last}",
        )
    return "healthy", cause("active", "Active on its host, and its keeper answers there.")


def _remembered(
    failed: dict[str, str], memory: dict[str, Any] | None, now: float
) -> dict[str, str]:
    if not memory:
        return failed
    last = (
        f" Last seen {memory.get('active', 'read')} {age(now - float(memory.get('at', now)))} ago."
    )
    return {**failed, "text": failed["text"] + last}


def _central(
    book: Book,
    central: CentralAnswer | None,
    raw: list[dict[str, Any]],
    keeper: KeeperAnswer | None,
    vantages: list[tuple[str, Any]],
    seen: dict[str, dict[str, Any]],
    facility: dict[str, Any],
    now: float,
    reach: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """The central host's card, and what the keeper's health was judged to be.

    `reach` is whether the central host itself answered, from whichever
    login reached it, so a host that is up reads apart from its services. Its
    network is the routable one, where `docs/beamlines/index.md` places the
    keeper.
    """
    entries: dict[str, dict[str, Any]] = {}
    for item in raw:
        entries[item["unit"].name.removesuffix(".service")] = item
    if central is not None and not central.unreachable:
        for unit in central.units:
            entries.setdefault(
                unit.name.removesuffix(".service"),
                {
                    "unit": unit,
                    "host": unit.condition or book.central_host,
                    "active": unit.active,
                    "said": "",
                },
            )
    keeper_unit = entries.get("cora-keeper")
    keeper_health, keeper_why = _judge_keeper(
        keeper, vantages, keeper_unit["active"] if keeper_unit else None
    )
    listing_read = bool(entries) or (central is not None and not central.unreachable)
    parts: list[dict[str, Any]] = []
    stems = list(ON_THE_CENTRAL_HOST) + sorted(set(entries) - set(ON_THE_CENTRAL_HOST))
    for stem in stems:
        name = stem + ".service"
        item = entries.get(stem)
        memory = seen.get(f"central/{name}")
        if item is not None:
            health, why = from_systemd(item["unit"].enabled, item["active"], item["said"])
            host = str(item["host"])
        elif listing_read:
            health, why = (
                "notinstalled",
                cause("no unit anywhere", "No account that was read holds a unit for it."),
            )
            host = ""
        else:
            failed = cause(
                "not read",
                "No account listing the central host's units was read this round.",
            )
            health, why = "unknown", _remembered(failed, memory, now)
            host = str(memory["host"]) if memory else book.central_host
        if stem == "cora-keeper" and keeper_health != "unknown":
            health, why = keeper_health, keeper_why
        parts.append(
            _part(
                name,
                where=place(host, None, book.central_host) if host else "nowhere",
                host=host,
                health=health,
                why=why,
                seams=_seams(stem, {}, None, facility),
                found=stem not in ON_THE_CENTRAL_HOST,
            )
        )
    level = "ok"
    if any(part["health"] == "down" for part in parts):
        level = "fault"
    elif any(part["health"] == "unknown" for part in parts):
        level = "unknown"
    for part in parts:
        part["role"] = "central host" if part["host"] else ""
    name = _short(book.central_host)
    host_entry: dict[str, Any] = {
        "name": name,
        "role": "central host",
        "network": "routable",
        "reached": None if reach is None else bool(reach.get("reached")),
        "uptime": None if reach is None else reach.get("uptime"),
        "why": "" if reach is None or reach.get("reached") else "could not be asked",
        "parts": [part["id"] for part in parts if part["host"]],
    }
    card = {
        "slug": "central",
        "title": "Central",
        "hosts": [host_entry] if name else [],
        "host": book.central_host,
        "url": keeper.url if keeper else None,
        "version": keeper.version if keeper else None,
        "ready": keeper.ready if keeper else None,
        "parts": parts,
        "level": level,
        "keeper": {"health": keeper_health, "cause": keeper_why},
        "asked": None if central is None else {"at": central.asked_at, "seconds": central.seconds},
    }
    return card, keeper_health


def _fleet(hosts: dict[str, HostAnswer]) -> dict[str, Any]:
    revisions: dict[str, list[str]] = {}
    for slug, answer in sorted(hosts.items()):
        if answer.report.unreachable:
            continue
        sha = answer.report.revisions.get("conductor", "unnamed")
        revisions.setdefault(sha[:7], []).append(slug)
    reasons: list[dict[str, str]] = []
    if len(revisions) > 1:
        spread = "; ".join(
            f"{sha} at {', '.join(slugs)}" for sha, slugs in sorted(revisions.items())
        )
        reasons.append(
            {
                "level": "attention",
                "source": "hosts",
                "text": f"the conductors are on {len(revisions)} revisions: {spread}",
            }
        )
    return {
        "revisions": revisions,
        "reasons": reasons,
        "level": "attention" if reasons else "ok",
    }


def _sources(
    tree: dict[str, Any],
    book: Book,
    cards: list[dict[str, Any]],
    keeper: KeeperAnswer | None,
    keeper_health: str,
    keeper_why: dict[str, str],
    vantages: list[tuple[str, Any]],
    unasked: int,
) -> list[dict[str, Any]]:
    """Whether each source this page reads could be read, and what to do when not."""
    behind = tree.get("behind_main")
    registers: dict[str, Any] = {
        "id": "tree",
        "name": "Registers",
        "via": "beamlines/ in this checkout",
        "state": "partial" if behind else "reading",
        "why": f"Read at {str(tree['revision'] or 'an unnamed revision')[:7]}."
        + (
            f" This checkout is {behind} commits behind main, so registers may be stale."
            if behind
            else ""
        ),
        "fix": None,
    }
    reached = [card["slug"] for card in cards if card["reached"]]
    failed = [card for card in cards if not card["reached"]]
    tags = Counter(card["failed"]["tag"] for card in failed if card["failed"])
    why = (
        f"Reached {len(reached)} of {len(cards)} beamlines."
        + ("".join(f" {count} {tag}." for tag, count in tags.items()))
        + (f" {unasked} components pinned elsewhere went unasked." if unasked else "")
    )
    fix = None
    if "login refused" in tags:
        fix = {
            "label": "Load the key into the agent once per login session",
            "run": "ssh-add ~/.ssh/<key>",
        }
    elif "host not named" in tags:
        fix = {
            "label": "Name the conductor host in the address book",
            "run": '[beamline."<slug>"]\nconductor = "<host>"',
        }
    hosts_state = "reading" if not failed and not unasked else "partial" if reached else "cannot"
    host_source = {
        "id": "hosts",
        "name": "Host probe",
        "via": "ssh, one login per beamline",
        "state": hosts_state,
        "why": why,
        "fix": fix,
    }

    if keeper is not None and keeper.error is None:
        keeper_state, keeper_text = "reading", f"Read at {keeper.url}, version {keeper.version}."
    elif keeper is not None:
        keeper_state, keeper_text = "cannot", f"Not readable from here: {keeper.error}."
    else:
        keeper_state, keeper_text = (
            "cannot",
            "No keeper address was given, so the record is not read.",
        )
    if vantages:
        answering = sum(1 for _, reach in vantages if reach.answers)
        keeper_text += f" It answers {answering} of {len(vantages)} conductor hosts that asked."
        if keeper_state == "cannot" and answering:
            keeper_state = "partial"
            keeper_text = (
                f"Seen answering from {answering} of {len(vantages)} conductor hosts. This page "
                "has no address for it, so its record of work is not read."
            )
    keeper_fix = None
    if keeper_health == "down":
        keeper_fix = {
            "label": "A write: on the central host, as the account that owns its units, after "
            "pausing any conductor that drives a real station",
            "run": "systemctl --user daemon-reload\n"
            "systemctl --user start cora-keeper-postgres cora-keeper-jwks cora-keeper",
        }
    keeper_source = {
        "id": "keeper",
        "name": "Keeper record",
        "via": "HTTPS, from here and from each conductor host",
        "state": keeper_state if keeper_health != "down" else "cannot",
        "why": (keeper_why["text"] + " " if keeper_health == "down" else "") + keeper_text,
        "fix": keeper_fix,
    }
    gaps = [f"no conductor host for {slug}" for slug in sorted(book.missing)]
    if not book.central_host:
        gaps.append("no central host")
    book_source = {
        "id": "book",
        "name": "Address book",
        "via": "beamlines/hosts.toml, untracked",
        "state": "partial" if gaps else "reading",
        "why": ("Missing: " + "; ".join(gaps) + ".")
        if gaps
        else "Names a host for every beamline.",
        "fix": None,
    }
    return [registers, host_source, keeper_source, book_source]


def _verdict(
    central: dict[str, Any], cards: list[dict[str, Any]], keeper_health: str
) -> dict[str, Any]:
    parts = [p for p in central["parts"] if not p["external"]] + [
        p for card in cards for p in card["parts"] if not p["external"]
    ]
    down = [p for p in parts if p["health"] == "down"]
    degraded = [p for p in parts if p["health"] == "degraded"]
    read = [p for p in parts if p["health"] in OBSERVED]
    groups = Counter(p["cause"]["tag"] for p in down + degraded)
    detail = "; ".join(f"{count} {tag}" for tag, count in groups.most_common(3))
    if keeper_health == "down":
        state, title = "down", "Keeper down"
        lead = "The keeper is down, so no beamline can take work."
        detail = central["keeper"]["cause"]["text"] + (f" Elsewhere: {detail}." if detail else "")
    elif down:
        state, title = "down", f"{len(down)} service{'s' if len(down) != 1 else ''} down"
        lead = f"{len(down)} component{'s are' if len(down) != 1 else ' is'} down."
    elif degraded:
        state, title = "degraded", "Running, with warnings"
        are = "s are" if len(degraded) != 1 else " is"
        lead = f"{len(degraded)} component{are} running but degraded."
    elif not read:
        state, title = "unknown", "Not visible"
        lead = "The monitor cannot see the installation yet."
        detail = "Nothing was read this round; the sources below say why."
    else:
        state, title = "healthy", "All running"
        lead = "Every component that answered is healthy."
    hosts = [host for card in [central, *cards] for host in card.get("hosts", [])]
    counts = {
        "down": len(down),
        "degraded": len(degraded),
        "read": len(read),
        "running": sum(1 for part in parts if part["health"] == "healthy"),
        "total": len(parts),
        "hosts": len(hosts),
        "hosts_up": sum(1 for host in hosts if host["reached"]),
    }
    return {"state": state, "title": title, "lead": lead, "detail": detail, "counts": counts}


def _sector(slug: str) -> tuple[int, str]:
    head = slug.split("-")[0]
    return (int(head) if head.isdigit() else 999, slug)


def fold(
    tree: dict[str, Any],
    book: Book,
    hosts: dict[str, HostAnswer],
    central: CentralAnswer | None,
    keeper: KeeperAnswer | None,
    *,
    now: float,
    stale_hours: float = DEFAULT_STALE_HOURS,
    seen: dict[str, dict[str, Any]] | None = None,
    distance: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Everything the page draws, judged, from what the sources last said.

    Pure, so every judgement on the page can be tested without a host or a
    keeper, and the page does no judging of its own: it colours what this
    returns and nothing else.
    """
    seen = seen or {}
    distance = distance or {}
    slugs = sorted(tree["beamlines"], key=_sector)
    vantages = [
        (slug, hosts[slug].report.keeper)
        for slug in slugs
        if slug in hosts
        and not hosts[slug].report.unreachable
        and hosts[slug].report.keeper is not None
    ]
    raw: list[dict[str, Any]] = []
    for slug in slugs:
        answer = hosts.get(slug)
        if answer is None or answer.report.unreachable:
            continue
        for unit in answer.report.units:
            if _is_central(unit.condition, book):
                host, active, said = answer.elsewhere.get(
                    unit.name, (unit.condition, unit.active, "")
                )
                raw.append({"unit": unit, "host": host, "active": active, "said": said})
    reach: dict[str, Any] | None = None
    if central is not None:
        reach = {"reached": not central.unreachable, "uptime": central.uptime}
    for answer in hosts.values():
        for host, said in answer.pinned.items():
            if _is_central(host, book) and (reach is None or not reach["reached"]):
                reach = {"reached": bool(said.get("reached")), "uptime": said.get("uptime")}
    central_card, keeper_health = _central(
        book, central, raw, keeper, vantages, seen, tree.get("facility") or {}, now, reach
    )
    keeper_down = keeper_health == "down"
    cards: list[dict[str, Any]] = []
    disagreements: list[dict[str, str]] = []
    for slug in slugs:
        card, found = _beamline(
            slug, tree, book, hosts.get(slug), keeper, seen, distance, keeper_down, now, stale_hours
        )
        cards.append(card)
        disagreements.extend(found)
    unasked = sum(
        1
        for answer in hosts.values()
        for _, active, _ in answer.elsewhere.values()
        if active == "unasked"
    )
    fleet = _fleet(hosts)
    for reason in fleet["reasons"]:
        disagreements.insert(
            0,
            {
                "where": "the deployed fleet",
                "text": reason["text"][0].upper() + reason["text"][1:] + ".",
                "decide": "Which revision the fleet should be on.",
            },
        )
    verdict = _verdict(central_card, cards, keeper_health)
    verdict["counts"]["disagreements"] = len(disagreements)
    unplaced = [
        [part["unit"], f"{card['title']}, {part['where']}"]
        for card in [central_card, *cards]
        for part in card["parts"]
        if part["found"] and part["unit"]
    ]
    return {
        "taken_at": now,
        "tree": {
            "revision": tree["revision"],
            "behind_main": tree.get("behind_main"),
            "operations": tree["operations"],
            "away": tree["away"],
            "facility": tree.get("facility") or {},
        },
        "lanes": [{"ops": list(ops), "lane": lane, "name": name} for ops, lane, name in LANES],
        "verdict": verdict,
        "sources": _sources(
            tree,
            book,
            cards,
            keeper,
            keeper_health,
            central_card["keeper"]["cause"],
            vantages,
            unasked,
        ),
        "central": central_card,
        "beamlines": cards,
        "fleet": fleet,
        "disagreements": disagreements,
        "unplaced": unplaced,
    }


def commands(slug: str, target: Target | None, pinned_hosts: list[str]) -> list[dict[str, str]]:
    """What a person would type next, filled in for this beamline. None writes.

    Every remote command is fed to bash on its standard input, because one
    beamline account logs in to tcsh, where a command substitution is an
    error. Units pinned to another host are reached through the conductor
    host, the way the page itself asks them.
    """
    if target is None:
        return []
    t = target.ssh
    journal = "journalctl --user -u cora-conductor --since -1h --no-pager"
    listed = 'systemctl --user list-units "cora-*" --all --no-pager'
    found = [
        {
            "label": "Every cora unit on the conductor's host",
            "run": f"ssh {t} bash -s <<< '{listed}'",
        },
        {
            "label": "The conductor's journal for the last hour",
            "run": f"ssh {t} bash -s <<< '{journal}'",
        },
        {
            "label": "What the running conductor searches and sends with",
            "run": f"ssh {t} bash -s <<< '{_ENVIRON_READ}'",
        },
        {
            "label": "This beamline against the registers",
            "run": f"uv run beamlines/verify_hosts.py --host {slug}={t}",
        },
    ]
    for host in pinned_hosts:
        found.append(
            {
                "label": f"The units pinned to {host}, through the conductor host",
                "run": f"ssh -J {t} {target.on(host)} bash -s <<< '{listed}'",
            }
        )
    return found


def _refusal(path: Path, what: str) -> str | None:
    """Why `what` may not be written at `path`, or None when it may."""
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(TREE_ROOT):
        return None
    ignored = subprocess.run(
        ["git", "-C", str(TREE_ROOT), "check-ignore", "-q", str(resolved)], check=False
    )
    if ignored.returncode == 0:
        return None
    return (
        f"{path} is inside the tree where git would see it, and {what} carries host "
        "names. Write it outside the tree"
    )


def snapshot_refusal(path: Path) -> str | None:
    """Why a snapshot may not be written at `path`, or None when it may.

    A snapshot carries host names and accounts, which the coordinate rule
    keeps out of every tracked file. Inside the tree it is allowed only
    where git ignores it, so it cannot be staged by accident.
    """
    return _refusal(path, "a snapshot")


def read_seen(path: Path | None) -> dict[str, dict[str, Any]]:
    """The remembered inventory, or nothing when there is none or it does not parse."""
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    entries = cast("dict[str, Any]", raw)
    return {
        str(key): cast("dict[str, Any]", value)
        for key, value in entries.items()
        if isinstance(value, dict)
    }


def write_seen(path: Path, seen: dict[str, dict[str, Any]]) -> None:
    """Replace the remembered inventory whole, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(seen, indent=1, sort_keys=True), encoding="utf-8")
    partial.replace(path)


class Fleet:
    """The three sources, the threads that ask them, and the last answers."""

    def __init__(
        self,
        book: Book,
        keeper: Keeper | None,
        ssh_opts: list[str],
        stale_hours: float,
        host_interval: float,
        seen_path: Path | None = None,
    ) -> None:
        self.book = book
        self.keeper = keeper
        self.ssh_opts = ssh_opts
        self.stale_hours = stale_hours
        self.host_interval = host_interval
        self.seen_path = seen_path
        self.seen = read_seen(seen_path)
        self.hosts: dict[str, HostAnswer] = {}
        self.central: CentralAnswer | None = None
        self.keeper_answer: KeeperAnswer | None = None
        self.asking = False
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self._distance: dict[str, int | None] = {}
        self._tree = read_tree(BEAMLINES)
        self._tree_error: str | None = None

    def ask_hosts(self) -> None:
        with self._lock:
            self.asking = True
        jobs = len(self.book.targets) + 1
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            pending: dict[Any, Callable[[Any], None]] = {}
            for slug, target in self.book.targets.items():
                future = pool.submit(ask_beamline, slug, target, self.ssh_opts)
                pending[future] = lambda answer, slug=slug: self._keep_host(slug, answer)
            if self.book.central is not None:
                future = pool.submit(ask_central, self.book.central, self.ssh_opts)
                pending[future] = self._keep_central
            for future in as_completed(pending):
                pending[future](future.result())
        with self._lock:
            self.asking = False

    def _keep_host(self, slug: str, answer: HostAnswer) -> None:
        for revision in answer.report.revisions.values():
            if revision not in self._distance:
                self._distance[revision] = distance_to_head(TREE_ROOT, revision)
        with self._lock:
            self.hosts[slug] = answer
            self.seen = merged(self.seen, observed_from(slug, answer, self.book), time.time())
            seen = dict(self.seen)
        if self.seen_path is not None:
            try:
                write_seen(self.seen_path, seen)
            except OSError as error:
                print(f"the inventory could not be remembered: {error}", file=sys.stderr)

    def _keep_central(self, answer: CentralAnswer) -> None:
        with self._lock:
            self.central = answer

    def ask_keeper(self) -> None:
        if self.keeper is None:
            return
        answer = ask_keeper(self.keeper, sorted(self._tree["beamlines"]))
        with self._lock:
            self.keeper_answer = answer

    def host_loop(self) -> None:
        """Ask the hosts, wait, and ask again, surviving whatever one round raises.

        A page left open all shift must not stop asking because one round met
        a register mid-edit, so a failure is printed and the next round runs.
        """
        while not self.stopping.is_set():
            try:
                self.ask_hosts()
            except Exception as error:
                print(f"a host round failed and the next one will run: {error}", file=sys.stderr)
                with self._lock:
                    self.asking = False
            self.wake.wait(self.host_interval)
            self.wake.clear()

    def keeper_loop(self, interval: float) -> None:
        while not self.stopping.is_set():
            try:
                self.ask_keeper()
            except Exception as error:
                print(f"a keeper round failed and the next one will run: {error}", file=sys.stderr)
            self.stopping.wait(interval)

    def state(self) -> dict[str, Any]:
        try:
            self._tree = read_tree(BEAMLINES)
            self._tree_error = None
        except (DescriptorError, OSError, tomllib.TOMLDecodeError) as error:
            self._tree_error = (
                f"the registers did not load, so the last good read is shown: {error}"
            )
        with self._lock:
            state = fold(
                self._tree,
                self.book,
                dict(self.hosts),
                self.central,
                self.keeper_answer,
                now=time.time(),
                stale_hours=self.stale_hours,
                seen=dict(self.seen),
                distance=dict(self._distance),
            )
            state["clock"] = {
                "asking": self.asking,
                "interval": self.host_interval,
                "watched": bool(self.book.targets),
                "keeper_at": self.keeper_answer.asked_at if self.keeper_answer else None,
                "tree_error": self._tree_error,
                "stale_hours": self.stale_hours,
                "remembered": len(self.seen),
            }
        return state


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CORA facility status</title>
<style>
  :root {
    color-scheme: light;
    --plane: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --wash: rgba(11,11,11,0.04);
    --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
      --unknown: #898781;
    --on-fill: #ffffff; --on-warning: #0b0b0b;
    --sans: system-ui, -apple-system, "Segoe UI", sans-serif;
    --mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --plane: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7;
      --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
        --wash: rgba(255,255,255,0.05);
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --plane: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
      --wash: rgba(255,255,255,0.05);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--plane); color: var(--ink); font: 14px/1.5 var(--sans); }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 0 24px 64px; }
  button, .switch { font: inherit; font-size: 13px; color: var(--ink); }
  button {
    background: transparent; border: 1px solid var(--border); border-radius: 7px;
    padding: 5px 12px; cursor: pointer;
  }
  button:hover { background: var(--wash); }
  button:disabled { color: var(--muted); cursor: default; }
  :focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .quiet { color: var(--ink-2); }
  .muted { color: var(--muted); }
  .small { font-size: 12.5px; }
  .mono { font-family: var(--mono); font-size: 12.5px; }

  /* masthead */
  .masthead { display: flex; align-items: center; gap: 12px 20px; flex-wrap: wrap;
    padding: 22px 0 18px; }
  .wordmark { font-size: 15px; font-weight: 700; letter-spacing: 0.02em; }
  .wordmark span { font-weight: 450; color: var(--ink-2); letter-spacing: 0; margin-left: 8px; }
  .masthead .grow { flex: 1 1 auto; }
  .switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
    user-select: none; }
  .switch input { position: absolute; opacity: 0; pointer-events: none; }
  .switch .track {
    width: 30px; height: 18px; border-radius: 9px; background: var(--axis); position: relative;
    transition: background 120ms ease;
  }
  .switch .track::after {
    content: ""; position: absolute; top: 2px; left: 2px; width: 14px; height: 14px;
    border-radius: 50%; background: var(--surface); transition: transform 120ms ease;
  }
  .switch input:checked + .track { background: var(--ink-2); }
  .switch input:checked + .track::after { transform: translateX(12px); }
  .switch input:focus-visible + .track { outline: 2px solid var(--ink); outline-offset: 2px; }

  /* status icons: a shape and a glyph, so state never rides on colour alone */
  .t-good { --c: var(--good); --g: var(--on-fill); }
  .t-warning { --c: var(--warning); --g: var(--on-warning); }
  .t-serious { --c: var(--serious); --g: var(--on-fill); }
  .t-critical { --c: var(--critical); --g: var(--on-fill); }
  .t-unknown { --c: var(--unknown); --g: var(--on-fill); }
  .t-ink { --c: var(--ink-2); --g: var(--on-fill); }
  .ic-fill { fill: var(--c); }
  .ic-line { fill: none; stroke: var(--c); stroke-width: 1.6; }
  .ic-glyph { fill: none; stroke: var(--g); stroke-width: 1.8; stroke-linecap: round;
    stroke-linejoin: round; }
  .ic-glyph-fill { fill: var(--g); }
  .ic-q { fill: var(--c); font: 700 10px var(--sans); }
  .chip { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .chip svg { flex: none; }

  /* hero: the ring and what it says */
  .hero {
    display: grid; grid-template-columns: minmax(0, 460px) minmax(0, 1fr); gap: 8px 48px;
    align-items: center; padding: 8px 0 36px; border-bottom: 1px solid var(--grid);
  }
  @media (max-width: 880px) { .hero { grid-template-columns: 1fr; } }
  .ring { width: 100%; height: auto; display: block; }
  .ring .sector { stroke: var(--axis); stroke-width: 1; }
  .ring .sector.taken { stroke: var(--ink-2); stroke-width: 1.5; }
  .ring .orbit { fill: none; stroke: var(--axis); stroke-width: 1.5; }
  .ring .beam { stroke: var(--ink-2); stroke-width: 2; stroke-linecap: round; }
  .ring .spoke { stroke: var(--axis); stroke-width: 1; }
  .ring .spoke.refused, .ring .spoke.unreachable, .ring .away.blocked, .ring .away.failing {
    stroke: var(--serious); stroke-dasharray: 4 4; stroke-width: 1.5;
  }
  .ring .spoke.unknown { stroke-dasharray: 1 4; stroke-linecap: round; }
  .ring .away { stroke: var(--axis); stroke-width: 1.5; stroke-dasharray: 2 3; fill: none; }
  .ring .away.proven, .ring .away.running { stroke: var(--good); stroke-dasharray: none; }
  .ring .node-frame { fill: var(--surface); stroke: var(--c); stroke-width: 2; }
  .ring .station { cursor: pointer; }
  .ring .station:hover .node-frame, .ring .station:focus .node-frame { stroke-width: 3; }
  .ring .station:focus { outline: none; }
  .ring .label { fill: var(--ink); font: 650 13px var(--sans); }
  .ring .sublabel { fill: var(--muted); font: 11.5px var(--sans); }
  .ring .tick-label { fill: var(--muted); font: 10px var(--sans); }
  .ring .facility { fill: var(--plane); stroke: var(--axis); }
  .ring-note { font-size: 12px; color: var(--muted); margin: 6px 0 0; max-width: 46ch; }
  .verdict h1 { font-size: 34px; line-height: 1.1; font-weight: 650; letter-spacing: -0.02em;
    margin: 10px 0 8px; }
  .verdict .lead { font-size: 16px; color: var(--ink-2); margin: 0 0 22px; max-width: 52ch; }
  .measures { display: grid; grid-template-columns: max-content 1fr; gap: 8px 22px; margin: 0;
    font-size: 14px; }
  .measures dt { color: var(--muted); }
  .measures dd { margin: 0; }
  .measures dd strong { font-weight: 650; }
  .seeing { margin-top: 22px; font-size: 12.5px; color: var(--muted); }
  .callout {
    margin-top: 14px; padding: 10px 12px; border-left: 3px solid var(--c);
      background: var(--surface);
    border-radius: 0 8px 8px 0; font-size: 13px;
  }
  .callout .why { color: var(--ink-2); margin: 2px 0 6px; }
  pre.run {
    margin: 4px 0 0; padding: 7px 9px; background: var(--plane); border: 1px solid var(--border);
    border-radius: 6px; font: 11.5px/1.45 var(--mono); white-space: pre-wrap;
      word-break: break-word;
  }
  .copy { font-size: 11.5px; padding: 1px 8px; margin-left: 8px; }

  /* sections */
  section { padding-top: 34px; }
  h2 { font-size: 17px; font-weight: 650; margin: 0 0 4px; letter-spacing: -0.01em; }
  .section-note { margin: 0 0 18px; color: var(--ink-2); font-size: 13px; max-width: 72ch; }

  /* the beamlines side by side */
  .matrix {
    display: grid; grid-auto-flow: column; grid-template-rows: repeat(var(--rows), auto);
    grid-template-columns: 112px repeat(var(--cols), minmax(0, 1fr)); column-gap: 0;
  }
  .cell { padding: 12px 16px 12px 0; border-top: 1px solid var(--grid); min-width: 0; }
  .cell.col { padding-left: 16px; border-left: 1px solid var(--grid); }
  .cell.head { border-top: 0; padding-top: 0; }
  .cell.label { color: var(--muted); font-size: 12.5px; padding-top: 14px; }
  .cell .inline { display: none; }
  .bl-name { font-size: 22px; font-weight: 650; letter-spacing: -0.01em; display: block; }
  .bl-state { display: flex; align-items: center; justify-content: space-between; gap: 8px;
    margin-top: 4px; }
  .bl-state button { font-size: 12px; padding: 2px 10px; }
  .net { display: flex; flex-direction: column; }
  .uplink { display: flex; align-items: center; gap: 7px; padding-left: 12px; font-size: 12.5px; }
  .uplink .state { color: var(--muted); margin-left: auto; }
  .wire { height: 14px; margin-left: 18px; border-left: 2px solid var(--axis); }
  .wire.broken { border-left-style: dashed; border-left-color: var(--serious); }
  .wire.unknown { border-left-style: dotted; }
  .pc {
    border: 1px solid var(--border); border-radius: 9px; padding: 8px 10px 9px;
    background: var(--surface);
  }
  .pc-head { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; }
  .pc-head .up { margin-left: auto; color: var(--muted); font-weight: 450; font-size: 12px;
    white-space: nowrap; }
  .pc-net { color: var(--muted); font-size: 12px; margin: 0 0 5px 26px; }
  .pc-icon { flex: none; color: var(--ink-2); }
  .pc-icon .screen, .pc-icon .stand-line { fill: none; stroke: currentColor; stroke-width: 1.4; }
  .pc-icon .badge { fill: var(--c); stroke: var(--surface); stroke-width: 2; }
  .minor { display: grid; grid-template-columns: max-content 1fr; gap: 3px 10px; margin: 6px 0 0;
    padding-top: 6px; border-top: 1px dashed var(--grid); font-size: 12px; color: var(--ink-2); }
  .pc-net + .minor { border-top: 0; padding-top: 0; }
  .minor dt { color: var(--muted); }
  .uplink a { color: inherit; text-decoration: none; }
  .uplink a:hover { text-decoration: underline; }
  .minor .said { color: var(--muted); }
  .minor dd { margin: 0; display: flex; flex-wrap: wrap; gap: 3px 12px; min-width: 0; }
  #central-helpers .minor { border-top: 1px solid var(--grid); padding-top: 10px; margin-top: 0; }
  .pc-head > span:not(.up) { min-width: 0; }
  .svc { display: flex; align-items: center; gap: 7px; padding: 3px 0 0 2px; font-size: 13.5px; }
  .svc .tag { color: var(--muted); font-size: 12px; margin-left: auto; text-align: right; }
  .svc.external { color: var(--muted); }
  .ops { display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .ops .chip { font-size: 12.5px; }
  .ops .absent { color: var(--muted); }
  @media (max-width: 860px) {
    .matrix { grid-auto-flow: row; grid-template-columns: 1fr; grid-template-rows: none; }
    .cell.label { display: none; }
    .cell.col { border-left: 0; padding-left: 0; }
    .cell .inline { display: block; color: var(--muted); font-size: 12px; margin-bottom: 2px; }
    .cell.head { padding-top: 28px; border-top: 2px solid var(--ink-2); margin-top: 6px; }
  }

  /* the central host */
  .central { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 0 28px; }
  .central .item { padding: 12px 0; border-top: 1px solid var(--grid); }
  .central .item .what { color: var(--muted); font-size: 12.5px; margin-top: 2px; }
  .central-host { display: flex; gap: 10px; align-items: baseline; margin-bottom: 8px;
    font-size: 13px; color: var(--ink-2); }

  /* notes */
  details.notes { border-top: 1px solid var(--grid); }
  details.notes > summary { cursor: pointer; padding: 14px 0; font-weight: 600; list-style: none; }
  details.notes > summary::-webkit-details-marker { display: none; }
  details.notes > summary .count { color: var(--muted); font-weight: 450; margin-left: 6px; }
  .note { padding: 8px 0 10px; border-top: 1px solid var(--grid); font-size: 13px; }
  .note .where { font-weight: 600; }
  .note .decide { color: var(--muted); }

  /* details panel */
  .scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.28); opacity: 0;
    pointer-events: none; transition: opacity 160ms ease; }
  .scrim.open { opacity: 1; pointer-events: auto; }
  aside.panel {
    position: fixed; top: 0; right: 0; bottom: 0; width: min(720px, 100vw);
      background: var(--plane);
    border-left: 1px solid var(--border); transform: translateX(100%);
      transition: transform 180ms ease;
    overflow-y: auto; padding: 22px 26px 48px; z-index: 5;
  }
  aside.panel.open { transform: none; }
  @media (prefers-reduced-motion: reduce) {
    aside.panel, .scrim, .switch .track, .switch .track::after { transition: none; } }
  .panel-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .panel-head h2 { font-size: 20px; margin: 0; }
  .panel-head .grow { flex: 1 1 auto; }
  .panel h3 { font-size: 13.5px; font-weight: 650; margin: 22px 0 8px; }
  .pairs { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; font-size: 13px;
    margin: 0; }
  .pairs dt { color: var(--muted); }
  .pairs dd { margin: 0; overflow-wrap: anywhere; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th { text-align: left; font-weight: 550; color: var(--muted); font-size: 11.5px; }
  td, th { padding: 6px 12px 6px 0; vertical-align: top; border-bottom: 1px solid var(--grid); }
  td { overflow-wrap: anywhere; }
  td .seam { display: block; }
  .scroll { overflow-x: auto; }
  .reasons { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; font-size: 13px; }
  .reasons li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }

  .tip {
    position: fixed; z-index: 10; pointer-events: none; max-width: 300px;
      background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 12.5px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.14);
  }
  .tip strong { display: block; font-size: 13px; }
  footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--grid);
    font-size: 12.5px; color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div class="wordmark">CORA<span>Facility status</span></div>
    <div class="grow"></div>
    <span class="small muted" id="clock"></span>
    <button id="ask" type="button">Check now</button>
    <label class="switch"><input type="checkbox" id="names"><span class="track"></span>Host
      names</label>
    <button id="theme" type="button">Theme: auto</button>
  </header>

  <div class="hero">
    <figure style="margin:0">
      <svg class="ring" id="ring" viewBox="0 0 440 440" role="img"
        aria-labelledby="ring-title"></svg>
      <figcaption class="ring-note">Each beamline sits at its sector around the storage ring. The
        line to the centre is its link to the keeper; a broken line means the link is
          down.</figcaption>
    </figure>
    <div class="verdict" id="verdict"></div>
  </div>

  <section>
    <h2>Beamlines</h2>
    <p class="section-note">The conductor sits where it can reach the keeper, the simulators beside
      the instruments. Each computer lists CORA's own services first, with helpers and testing
      copies beneath; a helper in trouble moves up. Testing copies are software versions of a
      beamline's motors and scan server, so a procedure runs without moving anything.</p>
    <div class="matrix" id="matrix"></div>
  </section>

  <section id="central-section">
    <h2>Central host</h2>
    <p class="section-note">The record every beamline writes to, and the agents that read it.</p>
    <div class="central-host" id="central-host"></div>
    <div class="central" id="central"></div>
    <div id="central-helpers"></div>
  </section>

  <section>
    <details class="notes" id="notes"></details>
  </section>

  <footer id="footer">Read only. Nothing here changes a host; commands are shown for a person to
    run.</footer>
</div>
<div class="scrim" id="scrim"></div>
<aside class="panel" id="panel" aria-hidden="true" aria-labelledby="panel-title"></aside>
<div class="tip" id="tip" hidden></div>
<script id="seed" type="application/json">null</script>
<script>
"use strict";
const SEED = JSON.parse(document.getElementById("seed").textContent);
const SVGNS = "http://www.w3.org/2000/svg";
const RING_SECTORS = 40;
const STATES = {
  healthy: ["good", "check", "Running"], degraded: ["warning", "triangle", "Degraded"],
  down: ["critical", "cross", "Down"], unknown: ["unknown", "question", "Unknown"],
  unmonitored: ["unknown", "slash", "Not monitored"], off: ["unknown", "hollow", "Off"],
  notinstalled: ["unknown", "hollow", "Not installed"],
  proven: ["good", "check", "Proven"], running: ["good", "half", "Running"],
  failing: ["critical", "cross", "Failing"], confirmed: ["ink", "half", "Ready"],
  declared: ["unknown", "hollow", "Declared"], absent: ["unknown", "hollow", "Not set up"],
  blocked: ["serious", "bar", "Blocked"],
  reading: ["good", "check", "Reading"], partial: ["warning", "triangle", "Partial"],
  cannot: ["critical", "cross", "Cannot read"],
  insync: ["good", "check", "Current"], drifted: ["warning", "triangle", "Behind"],
  syncunknown: ["unknown", "question", "Unknown"],
  ok: ["good", "check", "Answers"], refused: ["critical", "cross", "Refused"],
  unreachable: ["critical", "cross", "Unreachable"],
  attention: ["warning", "triangle", "Attention"], fault: ["critical", "cross", "Fault"],
};
const RANK = { down: 5, degraded: 4, unknown: 3, unmonitored: 1, notinstalled: 1, off: 1,
    healthy: 0 };
function opName(op) {
  return ((state.lanes || []).find(l => l.ops.includes(op)) || {}).name || op;
}
let state = null, lastBody = "", renderedAt = 0, openSlug = null;
let showNames = (() =>
    { try { return localStorage.getItem("cc-names") === "1"; } catch (e) { return false; } })();

function st(name) { return STATES[name] || STATES.unknown; }
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function shapes(kind) {
  const C = (r, cls) => s("circle", { cx: 8, cy: 8, r, class: cls });
  switch (kind) {
    case "check": return [C(7, "ic-fill"), s("polyline", { points: "4.6,8.3 7,10.6 11.4,5.6",
        class: "ic-glyph" })];
    case "triangle": return [s("path", { d: "M8 1.4 L15 14.2 H1 Z", class: "ic-fill" }),
      s("line", { x1: 8, y1: 6, x2: 8, y2: 9.6, class: "ic-glyph" }), s("circle", { cx: 8, cy: 12,
          r: 0.9, class: "ic-glyph-fill" })];
    case "cross": return [C(7, "ic-fill"), s("path",
        { d: "M5.4 5.4 L10.6 10.6 M10.6 5.4 L5.4 10.6", class: "ic-glyph" })];
    case "bar": return [C(7, "ic-fill"), s("line", { x1: 4.6, y1: 8, x2: 11.4, y2: 8,
        class: "ic-glyph" })];
    case "question": return [C(6.3, "ic-line"), s("text", { x: 8, y: 11.4, "text-anchor": "middle",
        class: "ic-q" }, "?")];
    case "slash": return [C(6.3, "ic-line"), s("line", { x1: 3.6, y1: 12.4, x2: 12.4, y2: 3.6,
        class: "ic-line" })];
    case "half": return [C(6.3, "ic-line"), s("path", { d: "M8 1.7 A6.3 6.3 0 0 0 8 14.3 Z",
        class: "ic-fill" })];
    default: return [C(6.3, "ic-line")];
  }
}
function icon(name, size) {
  const [tone, kind] = st(name);
  return s("svg", { width: size || 14, height: size || 14, viewBox: "0 0 16 16", class: "t-" +
      tone, "aria-hidden": "true" },
    shapes(kind));
}
function chip(name, label) { return h("span", { class: "chip" }, icon(name), label === undefined ?
    st(name)[2] : label); }
function copyButton(text) {
  const b = h("button", { type: "button", class: "copy" }, "Copy");
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      b.textContent = "Copied";
    } catch (e) {
      b.textContent = "Select it";
    }
    setTimeout(() => { b.textContent = "Copy"; }, 1500);
  });
  return b;
}
function duration(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 3600) return Math.max(1, Math.round(seconds / 60)) + " min";
  if (seconds < 172800) return Math.round(seconds / 3600) + " h";
  return Math.round(seconds / 86400) + " days";
}
function ago(at) { return at ? duration(Date.now() / 1000 - at) + " ago" : "not yet"; }
function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

/* Host names and accounts are facility coordinates: without the switch,
    they never reach the screen. */
let secrets = [];
function collectSecrets() {
  const found = new Set();
  for (const o of owners()) for (const host of o.hosts || []) if (host.name) found.add(host.name);
  for (const b of state.beamlines) {
    if (!b.target) continue;
    found.add(b.target.host.split(".")[0]);
    if (b.target.account) found.add(b.target.account);
  }
  if (state.central.host) found.add(state.central.host.split(".")[0]);
  secrets = [...found].filter(x => x && x.length > 2).sort((a, b) => b.length - a.length);
}
function scrub(text) {
  if (showNames || !text) return text;
  let out = String(text).replace(/https?:\/\/\S+/g, "the keeper's address");
  for (const name of secrets) out = out.replace(new RegExp("\\b" +
      name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
    "(\\.[A-Za-z0-9.-]+)?\\b", "g"), "a host");
  return out;
}
function hostLabel(host) {
  const role = host.role ? host.role[0].toUpperCase() + host.role.slice(1) : "Host";
  return showNames && host.name ? host.name : role;
}

function owners() { return [state.central].concat(state.beamlines); }
function ours(o) { return o.parts.filter(p => !p.external); }
function worst(o) { return ours(o).map(p => p.health).reduce((a, b) => ((RANK[b] ||
    0) > (RANK[a] || 0) ? b : a), "healthy"); }
function summaryOf(o) {
  const w = worst(o);
  return { health: w, word: w === "healthy" ? "Running" : st(w)[2] };
}

/* ---------- the ring ---------- */
const tip = document.getElementById("tip");
function showTip(evt, lines) {
  tip.replaceChildren(...lines.map((l, i) => i === 0 ? h("strong", {}, l) : h("div",
      { class: "quiet" }, l)));
  tip.hidden = false; placeTip(evt);
}
function placeTip(evt) {
  let x, y;
  if (evt.clientX !== undefined && evt.type.startsWith("pointer")) { x = evt.clientX +
      14; y = evt.clientY + 14; }
  else { const r = evt.currentTarget.getBoundingClientRect(); x = r.right + 8; y = r.top; }
  if (x + tip.offsetWidth > innerWidth - 8) x = Math.max(8, x - tip.offsetWidth - 28);
  if (y + tip.offsetHeight > innerHeight - 8) y = Math.max(8, innerHeight - tip.offsetHeight - 8);
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { tip.hidden = true; }
function hoverable(el, lines, onpick) {
  el.setAttribute("tabindex", "0"); el.setAttribute("role", "button");
  el.setAttribute("aria-label", lines.join(". "));
  el.addEventListener("pointerenter", e => showTip(e, lines));
  el.addEventListener("pointermove", placeTip);
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", e => showTip(e, lines));
  el.addEventListener("blur", hideTip);
  if (onpick) {
    el.addEventListener("click", onpick);
    el.addEventListener("keydown", e => { if (e.key === "Enter" ||
        e.key === " ") { e.preventDefault(); onpick(); } });
  }
}
function renderRing() {
  const svg = document.getElementById("ring");
  const cx = 220, cy = 220, R = 140, L = 64;
  const kids = [s("title", { id: "ring-title" },
      "The beamlines around the storage ring, each linked to the keeper at the centre")];
  kids.push(s("circle", { class: "orbit", cx, cy, r: R }));
  const taken = new Set(state.beamlines.map(b => b.sector));
  for (let n = 1; n <= RING_SECTORS; n++) {
    const a = (n - 1) / RING_SECTORS * 2 * Math.PI, inner = taken.has(n) ? R - 9 : R - 5;
    kids.push(s("line", { class: "sector" + (taken.has(n) ? " taken" : ""),
      x1: cx + inner * Math.sin(a), y1: cy - inner * Math.cos(a), x2: cx + R * Math.sin(a),
          y2: cy - R * Math.cos(a) }));
  }
  const central = state.central, keeperHealth = central.keeper.health;
  const stations = [];
  for (const b of state.beamlines) {
    const a = (b.sector - 1) / RING_SECTORS * 2 * Math.PI;
    const px = cx + R * Math.sin(a), py = cy - R * Math.cos(a);
    const sx = px + L * Math.cos(a), sy = py + L * Math.sin(a);
    stations.push({ b, a, px, py, sx, sy });
    kids.push(s("line", { class: "spoke " + b.keeper_link.state, x1: sx, y1: sy, x2: cx, y2: cy }));
  }
  for (const { b, a, sx, sy } of stations) {
    if (!b.offsite.length) continue;
    const ox = (sx - cx), oy = (sy - cy), len = Math.hypot(ox, oy);
    const fx = sx + ox / len * 46, fy = sy + oy / len * 46;
    const states = b.offsite.map(l => l.state);
    const tone = states.includes("failing") ? "failing" :
      states.every(x => x === "blocked") ? "blocked" :
      states.includes("proven") ? "proven" : "declared";
    kids.push(s("line", { class: "away " + tone, x1: sx, y1: sy, x2: fx, y2: fy }));
    const fac = s("g", {}, s("rect", { class: "facility", x: fx - 7, y: fy - 7, width: 14,
        height: 14, rx: 3 }));
    const legs = b.offsite.map(l => opName(l.op) + ": " +
        st(l.state)[2].toLowerCase()).join(", ");
    hoverable(fac, ["Computing facility", "From " + b.title + ". " + legs + "."], () =>
        openPanel(b.slug));
    kids.push(fac);
    const right = Math.sin(a) >= 0;
    kids.push(s("text", { class: "sublabel", x: fx + (right ? 12 : -12), y: fy + 4,
        "text-anchor": right ? "start" : "end" },
      "Computing facility"));
  }
  for (const { b, px, py, sx, sy, a } of stations) {
    kids.push(s("line", { class: "beam", x1: px, y1: py, x2: sx, y2: sy }));
    const sum = summaryOf(b);
    const up = ours(b).filter(p => p.health === "healthy").length;
    const g = s("g", { class: "station t-" + st(sum.health)[0] },
      s("circle", { class: "node-frame", cx: sx, cy: sy, r: 11 }),
      s("g", { transform: `translate(${sx - 7},${sy - 7})` }, icon(sum.health)));
    hoverable(g, [b.title + ": " + sum.word, up + " of " + ours(b).length + " services running",
      "Keeper link: " + st(b.keeper_link.state)[2].toLowerCase()], () => openPanel(b.slug));
    kids.push(g);
    const lx = sx + (Math.sin(a) >= 0 ? 16 : -16), ly = sy + (Math.cos(a) > 0.5 ? -8 :
        Math.cos(a) < -0.5 ? 18 : 4);
    const anchor = Math.sin(a) >= 0 ? "start" : "end";
    kids.push(s("text", { class: "label", x: lx, y: ly, "text-anchor": anchor }, b.title));
    kids.push(s("text", { class: "sublabel", x: lx, y: ly + 15, "text-anchor": anchor }, sum.word));
  }
  const kg = s("g", { class: "station t-" + st(keeperHealth)[0] },
    s("circle", { class: "node-frame", cx, cy, r: 30 }),
    s("g", { transform: `translate(${cx - 8},${cy - 18})` }, icon(keeperHealth, 16)),
    s("text", { class: "label", x: cx, y: cy + 14, "text-anchor": "middle" }, "Keeper"));
  hoverable(kg, ["Keeper: " + (keeperHealth === "healthy" ? "answering" :
      st(keeperHealth)[2].toLowerCase()),
    scrub(central.keeper.cause.text)], () => openPanel("central"));
  kids.push(kg);
  kids.push(s("text", { class: "sublabel", x: cx, y: cy + 48, "text-anchor": "middle" },
      "Central host"));
  svg.replaceChildren(...kids);
}

/* ---------- the verdict ---------- */
function renderVerdict() {
  const v = state.verdict, n = v.counts;
  const linked = state.beamlines.filter(b => b.keeper_link.state === "ok").length;
  const keeperWord = state.central.keeper.health === "healthy" ? "Answering" :
    state.central.keeper.health === "down" ? "Down" : "Not read";
  const measures = h("dl", { class: "measures" },
    h("dt", {}, "Services"), h("dd", {}, h("strong", {}, n.running + " of " + n.total), " running"),
    h("dt", {}, "Hosts"), h("dd", {}, h("strong", {}, n.hosts_up + " of " + n.hosts), " answering"),
    h("dt", {}, "Keeper"), h("dd", {}, h("strong", {}, keeperWord), linked ? ", reached from " +
        linked + " of " +
      state.beamlines.length + " beamlines" : ""));
  const out = [chip(v.state, ""), h("h1", {}, v.title), h("p", { class: "lead" }, v.lead),
      measures];
  const c = state.clock || {};
  const asked = Math.max(0, ...state.beamlines.map(b => (b.asked ? b.asked.at : 0)));
  out.push(h("div", { class: "seeing" }, SEED ? "Snapshot from " +
      new Date(state.taken_at * 1000).toLocaleString() + "." :
    asked ? "Hosts checked " + ago(asked) + ", and again every " + duration(c.interval) + "." :
        "Hosts not checked yet."));
  for (const src of state.sources) {
    if (src.state === "partial") {
      out.push(h("div", { class: "seeing" }, src.name + ": " + scrub(src.why)));
    }
    if (src.state !== "cannot") continue;
    out.push(h("div", { class: "callout t-" + st(src.state)[0] }, chip(src.state, src.name + ": " +
        st(src.state)[2].toLowerCase()),
      h("div", { class: "why" }, scrub(src.why)),
      src.fix && showNames ? [h("div", { class: "small quiet" }, src.fix.label,
          copyButton(src.fix.run)),
        h("pre", { class: "run" }, src.fix.run)] : null));
  }
  document.getElementById("verdict").replaceChildren(...out);
}

/* ---------- the beamlines side by side ---------- */
const NETWORKS = { routable: "Facility network", private: "Beamline network",
    unknown: "Network not named" };
function computer(reached) {
  const tone = reached ? "good" : "unknown";
  return s("svg", { width: 18, height: 16, viewBox: "0 0 18 16", class: "pc-icon t-" + tone,
      "aria-hidden": "true" },
    s("rect", { class: "screen", x: 1.5, y: 1.5, width: 13, height: 9, rx: 1.5 }),
    s("path", { class: "stand-line", d: "M8 10.5 V13.5 M5 14 H11" }),
    s("circle", { class: "badge", cx: 14.5, cy: 11.5, r: 3.2 }));
}
function wire(state) {
  return h("div", { class: "wire" + (state === "broken" ? " broken" : state === "unknown" ?
      " unknown" : "") });
}
/* The four packages lead; a helper or a testing copy joins them only when it is in trouble. */
const TROUBLE = new Set(["down", "degraded"]);
const TIER_ORDER = { main: 0, helper: 1, testing: 2 };
const TIER_WORDS = { helper: "Helper", testing: "For testing" };
function promoted(p) { return p.tier === "main" || TROUBLE.has(p.health); }
function byTier(parts) {
  return [...parts].sort((a, b) => (TIER_ORDER[a.tier] ?? 3) - (TIER_ORDER[b.tier] ?? 3));
}
/* Unknown is left to the computer's own line, which says why nothing was read. */
function quietChip(p) {
  const said = p.health !== "healthy" && p.health !== "unknown";
  return h("span", { class: "chip", title: (p.health === "healthy" ? "" : st(p.health)[2] +
      ". ") + p.description }, icon(p.health, 12), p.name,
    said ? h("span", { class: "said" }, st(p.health)[2].toLowerCase()) : null);
}
/* What the conductor scans with is its own setting, so it reads on its row until trouble. */
const ENGINE_NOTES = {
  station: ["real scans", "Drives the station's real TomoScan"],
  simulated: ["simulated scans", "Drives a simulated TomoScan, a software copy of the scan " +
      "server, so nothing moves"],
  none: ["no scan engine", "No scan engine is configured"],
};
function serviceRow(p, note) {
  const tag = p.health !== "healthy" ? h("span", { class: "tag" }, scrub(p.cause.tag)) :
    note ? h("span", { class: "tag", title: note[1] }, note[0]) : null;
  return h("div", { class: "svc" }, icon(p.health), p.name, tag);
}
function quietLines(parts) {
  const groups = [["Helpers", "helper"], ["For testing", "testing"]]
    .map(([label, tier]) => [label, parts.filter(p => p.tier === tier)])
    .filter(([, members]) => members.length);
  if (!groups.length) return null;
  return h("dl", { class: "minor" }, groups.map(([label, members]) => [h("dt", {}, label),
    h("dd", {}, members.map(quietChip))]));
}
function network(b) {
  const link = b.keeper_link.state;
  const words = { ok: "answers", refused: "refused", unreachable: "unreachable",
      unknown: "not asked" };
  const out = [h("div", { class: "uplink", title: "Whether this beamline's conductor reaches the " +
      "keeper on the central host, asked from the conductor's computer" },
    icon(link === "unknown" ? "unknown" : link), h("a", { href: "#central-section" }, "Keeper"),
    h("span", { class: "state" }, words[link] || link)),
    wire(link === "ok" ? "ok" : link === "unknown" ? "unknown" : "broken")];
  b.hosts.forEach((host, i) => {
    if (i) out.push(wire(host.reached ? "ok" : host.reached === false ? "broken" : "unknown"));
    const services = byTier(host.parts.map(id => b.parts.find(p => p.id === id)).filter(Boolean));
    const lead = services.filter(promoted);
    const rest = services.filter(p => !promoted(p));
    out.push(h("div", { class: "pc" },
      h("div", { class: "pc-head" }, computer(host.reached), hostLabel(host),
        h("span", { class: "up" }, host.reached ? "up " + duration(host.uptime) : host.why ||
            "not read")),
      h("div", { class: "pc-net" }, NETWORKS[host.network] || NETWORKS.unknown),
      lead.map(p => serviceRow(p, p.kind === "cora-conductor" ? ENGINE_NOTES[b.engine.kind] :
        null)), quietLines(rest)));
  });
  return h("div", { class: "net" }, out);
}
const ROWS = [
  ["head", ""], ["computers", "Computers"],
  ["devices", "Devices"], ["procedures", "Procedures"], ["ops", "Operations"], ["away", "Off site"],
  ["version", "Software"],
];
function cellFor(b, key) {
  const r = b.registers;
  switch (key) {
    case "head": {
      const sum = summaryOf(b);
      return [h("span", { class: "bl-name" }, b.title), h("div", { class: "bl-state" },
          chip(sum.health, sum.word),
        h("button", { type: "button", onclick: () => openPanel(b.slug) }, "Details"))];
    }
    case "computers": return network(b);
    case "devices": return r.devices.total + " in " + r.devices.groups.length + " groups";
    case "procedures": {
      const ok = r.procedures.filter(p => p.confirmed).length;
      return ok + " of " + r.procedures.length + " confirmed";
    }
    case "ops": return h("div", { class: "ops" }, state.lanes.map(l => {
      const leg = b.legs[l.lane] || { state: "absent" };
      return h("span", { class: "chip" + (leg.state === "absent" ? " absent" : "") },
          icon(leg.state), l.name);
    }));
    case "away": {
      if (!b.offsite.length) return h("span", { class: "muted" }, "None");
      const names = b.offsite.map(l => opName(l.op).toLowerCase());
      const list = names.length > 1 ?
        names.slice(0, -1).join(", ") + " and " + names.at(-1) : names[0];
      return "Computing facility: " + list;
    }
    case "version": {
      const v = b.version;
      if (v.state === "syncunknown") return h("span", { class: "muted" }, "Not read");
      return chip(v.state, v.state === "insync" ? "Current" : v.behind ? v.behind +
          " commits behind" : "Behind");
    }
  }
  return "";
}
function renderMatrix() {
  const m = document.getElementById("matrix");
  m.style.setProperty("--rows", ROWS.length);
  m.style.setProperty("--cols", state.beamlines.length);
  const cells = ROWS.map(([key, label]) => h("div", { class: "cell label" + (key === "head" ?
      " head" : "") }, label));
  for (const b of state.beamlines) for (const [key, label] of ROWS) {
    cells.push(h("div", { class: "cell col" + (key === "head" ? " head" : "") },
      key === "head" ? null : h("span", { class: "inline" }, label), cellFor(b, key)));
  }
  m.replaceChildren(...cells);
}

/* ---------- the central host ---------- */
function renderCentral() {
  const c = state.central, host = (c.hosts || [])[0];
  document.getElementById("central-host").replaceChildren(...(host ? [computer(host.reached),
    h("span", {}, hostLabel(host)), h("span", { class: "muted" }, host.reached ? "up " +
      duration(host.uptime) : host.reached === false ? "not reached" : "not read"),
    h("span", { class: "muted" }, NETWORKS[host.network] || "")] :
    [h("span", { class: "muted" }, "No central host named.")]));
  const items = byTier(ours(c)).filter(promoted).map(p => h("div", { class: "item" },
    h("div", {}, chip(p.health, p.name)), h("div", { class: "what" }, p.health === "healthy" ?
      p.description : st(p.health)[2] + ". " + p.description)));
  items.push(h("div", { class: "item" }, h("div", {}, chip("confirmed", "Operations")),
    h("div", { class: "what" }, [...new Set(state.tree.operations.map(opName))].join(", "))));
  const helpers = ours(c).filter(p => !promoted(p));
  document.getElementById("central").replaceChildren(...items);
  document.getElementById("central-helpers").replaceChildren(...[quietLines(helpers)]
    .filter(Boolean));
}

/* ---------- notes ---------- */
function renderNotes() {
  const list = state.disagreements;
  const el = document.getElementById("notes");
  const open = el.open;
  el.replaceChildren(h("summary", {}, "Notes", h("span", { class: "count" }, list.length ?
      String(list.length) : "none")),
    ...list.map(d => h("div", { class: "note" }, h("div", {}, h("span", { class: "where" },
        scrub(d.where)), " ",
      h("span", { class: "quiet" }, scrub(d.text))), d.decide ? h("div", { class: "decide" },
          "To decide: " + d.decide) : null)));
  el.open = open;
}

/* ---------- details panel ---------- */
const IDENT = /^[a-z][a-z0-9_]*$/;
function seamValue(v) { return IDENT.test(v) ? h("span", { class: "mono" }, v) : h("span",
    { class: "quiet" }, scrub(v)); }
function pairs(list) { return h("dl", { class: "pairs" }, list.flatMap(([k, v]) => [h("dt", {}, k),
    h("dd", {}, v)])); }
function reasons(o) {
  const groups = new Map();
  for (const p of o.parts) {
    if (p.health === "healthy" || p.external) continue;
    const g = groups.get(p.cause.tag) || { p, n: 0 };
    g.n += 1; groups.set(p.cause.tag, g);
  }
  if (!groups.size) return h("p", { class: "quiet small" }, "Every service here is running.");
  return h("ul", { class: "reasons" }, [...groups.values()].map(({ p, n }) => h("li", {},
      chip(p.health, n + " " +
    (n === 1 ? "service" : "services")), h("strong", {}, scrub(p.cause.tag)), h("span",
        { class: "quiet" }, scrub(p.cause.text)))));
}
function servicesTable(o) {
  return h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["Service", "On",
      "State", "What fills it"]
    .map(c => h("th", {}, c)))), h("tbody", {}, byTier(o.parts).map(p => h("tr", {},
    h("td", {}, h("strong", {}, p.name), TIER_WORDS[p.tier] ? h("div", { class: "muted small" },
        TIER_WORDS[p.tier]) : null, p.unit && showNames ? h("div", { class: "mono muted" },
        p.unit) : null),
    h("td", {}, p.external ? "the beamline's own hosts" : showNames ? p.hostname : (p.role ||
        "not read")),
    h("td", {}, chip(p.health), p.health === "healthy" ? null :
      h("div", { class: "muted small" }, scrub(p.cause.tag))),
    h("td", {}, p.seams.map(([k, v]) => h("span", { class: "seam" }, h("span", { class: "muted" },
        k + " "), seamValue(v)))))))));
}
function openPanel(slug) {
  openSlug = slug; renderPanel();
  document.getElementById("panel").classList.add("open");
  document.getElementById("panel").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("open");
  const close = document.getElementById("panel-close"); if (close) close.focus();
}
function closePanel() {
  openSlug = null;
  document.getElementById("panel").classList.remove("open");
  document.getElementById("panel").setAttribute("aria-hidden", "true");
  document.getElementById("scrim").classList.remove("open");
}
function renderPanel() {
  if (!openSlug || !state) return;
  const o = owners().find(x => x.slug === openSlug);
  if (!o) return;
  const sum = summaryOf(o);
  const out = [h("div", { class: "panel-head" }, h("h2", { id: "panel-title" },
      o.slug === "central" ? "Central host" : o.title),
    chip(sum.health, sum.word), h("div", { class: "grow" }),
    h("button", { type: "button", id: "panel-close", onclick: closePanel }, "Close"))];
  out.push(h("h3", {}, "What needs attention"), reasons(o));
  out.push(h("h3", {}, "Services"), servicesTable(o));
  out.push(h("h3", {}, "Computers"), pairs((o.hosts || []).map(host => [hostLabel(host),
    (NETWORKS[host.network] || NETWORKS.unknown) + ", " + (host.reached ? "up " +
        duration(host.uptime) :
      host.why || "not read") + ", " + host.parts.length + " services"])));
  if (o.slug !== "central") out.push(h("p", { class: "small muted" },
      "The beamline's own control system, " +
    "its IOCs and scan server, belongs to the beamline. " +
    "CORA reads its records but does not yet check " +
    "that they answer."));
  if (o.slug !== "central") {
    out.push(h("h3", {}, "Data path"), h("div", { class: "ops" }, state.lanes.map(l => {
      const leg = o.legs[l.lane] || { state: "absent", note: "" };
      return h("div", { class: "small", style: "min-width:150px;margin-bottom:8px" },
          chip(leg.state, l.name),
        h("div", { class: "muted" }, leg.note));
    })));
    const r = o.registers;
    out.push(h("h3", {}, "Set up for"), pairs([
      ["Devices", r.devices.total + ", grouped as " + r.devices.groups.map(([g, n]) => g + " " +
          n).join(", ")],
      ["Procedures", r.procedures.map(p => p.name + (p.confirmed ? "" :
          " (unconfirmed)")).join("; ") || "none"],
      ["Adapters", Object.entries(r.adapters).map(([k, v]) => k.split(".")[1] + " " +
          v).join(", ")],
      ["Keeper link", scrub(o.keeper_link.text)],
      ["Scan engine", o.engine.prefix ? o.engine.kind + ", " + o.engine.prefix : o.engine.kind],
    ]));
    if (o.record.read) out.push(h("h3", {}, "Recent work"), pairs([["Newest " + o.record.window,
      Object.entries(o.record.counts).map(([k, v]) => v + " " + k).join(", ") || "none"],
      ["Live", String(o.record.live.length)], ["Without a dataset", String(o.record.unfiled)]]));
    if (o.findings.length) out.push(h("ul", { class: "reasons" }, o.findings.map(f => h("li", {},
        chip(f.level),
      h("span", { class: "quiet" }, scrub(f.text))))));
    if (showNames && o.commands.length) out.push(h("h3", {}, "Commands, read only"),
        ...o.commands.map(c =>
      h("div", { style: "margin-bottom:10px" }, h("div", { class: "small quiet" }, c.label,
          copyButton(c.run)),
        h("pre", { class: "run" }, c.run))));
  } else {
    out.push(h("h3", {}, "Keeper"), pairs([["Judged", st(o.keeper.health)[2] + ". " +
        scrub(o.keeper.cause.text)],
      ["Address", showNames ? (o.url || "not given here") : "hidden"], ["Version", o.version ||
          "not read"]]));
  }
  document.getElementById("panel").replaceChildren(...out);
}

/* ---------- live updates ---------- */
function renderClock() {
  if (!state) return;
  const c = state.clock || {};
  document.getElementById("clock").textContent = SEED ? "Snapshot" : c.asking ? "Checking hosts" :
    "Keeper read " + ago(c.keeper_at || state.taken_at);
  const ask = document.getElementById("ask");
  ask.hidden = Boolean(SEED) || !c.watched;
  ask.disabled = Boolean(c.asking);
}
function render() {
  collectSecrets();
  renderRing(); renderVerdict(); renderMatrix(); renderCentral();
  renderNotes(); renderPanel(); renderClock();
}
function accept(next) {
  const body = JSON.stringify(Object.assign({}, next, { taken_at: 0, clock: null }));
  state = next;
  if (body !== lastBody ||
      Date.now() - renderedAt > 60000) { lastBody = body; renderedAt = Date.now(); render(); }
  else renderClock();
}
async function poll() {
  try {
    const response = await fetch("/state", { cache: "no-store" });
    if (response.ok) accept(await response.json());
  } catch (e) {
    document.getElementById("clock").textContent = "This page's own server stopped answering";
  }
  setTimeout(poll, POLL_SECONDS * 1000);
}
const THEMES = ["auto", "light", "dark"];
function applyTheme(name) {
  if (name === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", name);
  document.getElementById("theme").textContent = "Theme: " + name;
}
document.getElementById("theme").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(recall("cc-theme") || "auto") + 1) % THEMES.length];
  store("cc-theme", next); applyTheme(next);
});
document.getElementById("ask").addEventListener("click", async () => {
  document.getElementById("ask").disabled = true;
  try { await fetch("/ask", { method: "POST", headers: { "X-Fleet-Ask": "1" } }); } catch (e) {}
});
const namesBox = document.getElementById("names");
namesBox.checked = showNames;
namesBox.addEventListener("change", () => { showNames = namesBox.checked; store("cc-names",
    showNames ? "1" : "0"); if (state) render(); });
document.getElementById("scrim").addEventListener("click", closePanel);
document.addEventListener("keydown", e => { if (e.key === "Escape" && openSlug) closePanel(); });
applyTheme(recall("cc-theme") || "auto");
setInterval(renderClock, 10000);
if (SEED) accept(SEED); else poll();
</script>
</body>
</html>
""".replace("POLL_SECONDS", str(PAGE_POLL_SECONDS))

_SEED_SLOT = '<script id="seed" type="application/json">null</script>'


def page(state: dict[str, Any] | None) -> str:
    """The page, live when `state` is None and a fixed snapshot otherwise."""
    if state is None:
        return PAGE
    body = json.dumps(state).replace("</", "<\\/")
    return PAGE.replace(_SEED_SLOT, f'<script id="seed" type="application/json">{body}</script>')


def make_handler(fleet: Fleet, port: int) -> type[BaseHTTPRequestHandler]:
    names = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _addressed_here(self) -> bool:
            """Whether the browser asked for this server by a loopback name.

            Binding to the loopback keeps other machines out but not other
            pages: a name an attacker controls can be made to resolve to the
            loopback after it loads, and then reads this page as its own. The
            Host header is what that leaves different, so anything else is
            refused.
            """
            if self.headers.get("Host") in names:
                return True
            self._send(421, b"not this name", "text/plain")
            return False

        def do_GET(self) -> None:
            if not self._addressed_here():
                return
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self._send(200, page(None).encode(), "text/html; charset=utf-8")
            elif path == "/state":
                self._send(200, json.dumps(fleet.state()).encode(), "application/json")
            elif path == "/favicon.ico":
                self._send(204, b"", "text/plain")
            else:
                self._send(404, b"not here", "text/plain")

        def do_POST(self) -> None:
            """Ask the hosts sooner, which changes nothing on them.

            The custom header is the whole guard and it is enough for what it
            guards: a page on another origin cannot set it without a preflight
            this server never answers, so only this page can start a probe.
            """
            if not self._addressed_here():
                return
            if (
                urllib.parse.urlparse(self.path).path != "/ask"
                or self.headers.get("X-Fleet-Ask") != "1"
            ):
                self._send(403, b"refused", "text/plain")
                return
            fleet.wake.set()
            self._send(202, b"asking", "text/plain")

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            """Quiet, because the page polls and every poll would be a line."""

    return Handler


def _token(args: argparse.Namespace) -> str | None:
    if args.token_file:
        return Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    return os.environ.get("CORA_TOKEN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch the health of the CORA installation.")
    parser.add_argument("--url", default=os.environ.get("CORA_KEEPER_URL"))
    parser.add_argument("--token-file", help="A file holding a bearer token that may read.")
    parser.add_argument("--ca", help="A certificate for a keeper signed by its own CA.")
    parser.add_argument("--book", type=Path, default=DEFAULT_BOOK, help="The address book.")
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        metavar="SLUG=TARGET",
        help="Ask TARGET for SLUG, overriding the address book. Repeatable.",
    )
    parser.add_argument("--central", metavar="TARGET", help="Also list the central host's units.")
    parser.add_argument(
        "--beamline", action="append", default=[], help="Watch only these. Repeatable."
    )
    parser.add_argument(
        "--ssh-opts", default="", help="Passed to every ssh, as verify_hosts takes."
    )
    parser.add_argument(
        "--no-hosts", action="store_true", help="Read the keeper and the tree only."
    )
    parser.add_argument(
        "--seen",
        type=Path,
        default=DEFAULT_SEEN,
        metavar="FILE",
        help="Where the inventory of units seen is remembered, outside the tree.",
    )
    parser.add_argument("--host-interval", type=float, default=HOST_INTERVAL_SECONDS)
    parser.add_argument("--keeper-interval", type=float, default=KEEPER_INTERVAL_SECONDS)
    parser.add_argument("--stale-hours", type=float, default=DEFAULT_STALE_HOURS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--snapshot",
        type=Path,
        metavar="FILE",
        help="Ask every source once, write the page with the answers in it, and exit.",
    )
    args = parser.parse_args(argv)

    overrides: dict[str, str] = {}
    for pair in args.host:
        if "=" not in pair:
            print(f"error: --host wants SLUG=TARGET, got {pair!r}", file=sys.stderr)
            return 2
        slug, target = pair.split("=", 1)
        overrides[slug] = target

    for path, what in ((args.seen, "the remembered inventory"), (args.snapshot, "a snapshot")):
        refusal = _refusal(path, what) if path is not None else None
        if refusal:
            print(f"error: {refusal}", file=sys.stderr)
            return 2

    try:
        slugs = sorted(read_tree(BEAMLINES)["beamlines"])
    except DescriptorError as error:
        print(f"error: the registers do not load: {error}", file=sys.stderr)
        return 2
    if args.beamline:
        unknown = sorted(set(args.beamline) - set(slugs))
        if unknown:
            print(f"error: no register for {', '.join(unknown)}", file=sys.stderr)
            return 2
        slugs = sorted(args.beamline)
    book = read_book(args.book, slugs, overrides, args.central)
    if args.no_hosts:
        book = Book(
            missing={slug: "host probes are off for this page" for slug in slugs},
            central_host=book.central_host,
        )

    keeper = None
    if args.url:
        context = ssl.create_default_context(cafile=args.ca)
        keeper = Keeper(args.url, _token(args), context)

    seen_path = args.seen.expanduser() if args.seen else None
    fleet = Fleet(
        book, keeper, args.ssh_opts.split(), args.stale_hours, args.host_interval, seen_path
    )

    if args.snapshot is not None:
        fleet.ask_keeper()
        if book.targets or book.central:
            fleet.ask_hosts()
        try:
            args.snapshot.write_text(page(fleet.state()), encoding="utf-8")
        except OSError as error:
            print(f"error: could not write the snapshot: {error}", file=sys.stderr)
            return 2
        print(f"wrote {args.snapshot}")
        return 0

    # The port is claimed before any host is asked, so a page that cannot
    # serve sends no ssh logins on its way out.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(fleet, args.port))
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        print(
            f"error: port {args.port} is already in use, most likely by another copy of this "
            f"page. Open http://127.0.0.1:{args.port}, stop that copy, or pass --port",
            file=sys.stderr,
        )
        return 2

    threads = [
        threading.Thread(target=fleet.keeper_loop, args=(args.keeper_interval,), daemon=True)
    ]
    if book.targets or book.central:
        threads.append(threading.Thread(target=fleet.host_loop, daemon=True))
    for thread in threads:
        thread.start()

    asked = ", ".join(f"{slug} at {target.host}" for slug, target in sorted(book.targets.items()))
    print(f"fleet on http://127.0.0.1:{args.port}")
    print(f"  hosts   {asked or 'none'}")
    for slug, why in sorted(book.missing.items()):
        print(f"  {slug:7} {why}")
    print(f"  keeper  {args.url or 'not given'}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    fleet.stopping.set()
    fleet.wake.set()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
