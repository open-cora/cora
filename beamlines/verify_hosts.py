"""Compare what each beamline host is configured with against the registers.

    uv run beamlines/verify_hosts.py \
        --host 7-bm=<account>@<beamline-host> \
        --host 19-bm=<account>@<beamline-host> \
        --revision "$(git rev-parse HEAD)"

A beamline whose host takes no inbound connection is reached through
one that does, which is what --ssh-opts carries:

    uv run beamlines/verify_hosts.py \
        --host 2-bm=<account>@<private-host> --ssh-opts "-J <routable-host>"

The targets are in the deployment address book, not here. See
beamlines/hosts.example.toml for why a machine's name is not written
into a published file.

Read-only. It runs `ssh` and reads six things per host, and writes
nothing anywhere: the revisions, the conductor's configuration, the
listed part of the running conductor's environment, the account's
units, whether the keeper the conductor is configured with answers
from that host, and how many errors the conductor has logged in the
last ten minutes. The keeper is asked for its health with no
credential, the same anonymous read anyone on that network can make.
`tools/cora_fleet.py` draws the same answer on a page.

## Why this is separate from verify_state.py

That one compares the descriptors against the keeper, which is one
database reachable over HTTPS. This compares them against files on four
machines in four accounts, reachable only by ssh, and the agreements it
checks are ones no database holds.

Both exist because the same question has two halves. A procedure that
cannot run is either a procedure the keeper does not have or a conductor
configured not to run it, and until now only the first half had a check.

## The four things it compares

**The revision.** Each install leaves a REVISION naming the commit. The
fleet drifted to three different revisions without anything reporting
it, which is visible here and nowhere else.

**The routine against the operation register.** A conductor refuses a
routine it was not told about, so `run.routines` has to hold the name
`beamlines/operations.toml` declares. A mismatch refuses every dispatch
at that beamline, correctly, for a reason no test can anticipate. This
is not hypothetical: renaming the operation and updating only the
register is exactly what happened, and four scans came back Refused.

**The writable scopes against what a confirmed procedure sets.** A set
step's record has to sit inside that conductor's `control.writable` or
the step is refused, because `EpicsControl` is handed that fence and
checks every write against it.

**The engine's prefix against what a confirmed procedure claims.** This
one is the opposite shape and it took a near miss to write down.
`control.writable` reaches exactly one place in the conductor, which is
`EpicsControl`, and that serves the set routine. **Nothing compares a run
step's scopes to anything at all.** A claim is a ledger lock that stops
two walks in one process sharing a device; it is not a fence on the
engine, and the engine drives whatever `run.prefix` points it at.

So a run step whose scopes name one namespace while the engine is
pointed at another does not fail. It takes a claim that protects
nothing, runs on the prefix, and reports success. That is how a row
reading as a simulation comes to drive a station: the deployment is
repointed, the procedure is not, and a procedure cannot be retired.

This file has now had that consequence wrong in both directions. It
said "that step is refused" before anything refused it, which told a
reader the system was stopping the thing it was running. Then the
conductor gained a station fence and began declining it, and this went
on saying it was not refused.

So what is reported is the disagreement, and both of the things it can
cost, and the fix they share. A message that states one consequence is
a message that goes stale the next time the other side changes, and
the other side is a different repository that ships on its own.

**The arming against what a reboot would restore.** A unit that is running
and not enabled disappears at the next reboot of its host, and a unit
enabled with no `ConditionHost` starts on every lingering host in the
account. Both read as healthy in `is-active`, and both have happened here.

This one covers the whole account from a single host, which the other
three cannot. A beamline's `~/.config/systemd/user` is one NFS directory
mounted by every machine in that account, so `is-enabled` and each unit's
`ConditionHost` are the same answer wherever they are asked. Asking the
conductor's host reports on the simulator's host too.

## What it cannot check

The token. A configuration now names a path rather than holding a
credential, which is what makes reading one safe, and this deliberately
does not read what the path points at.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Appended, never put first: first, this directory's `tests` shadows the
# tree's own, and a suite that imported the fleet page before
# `tests._tracked` failed to collect.
if str(Path(__file__).parent) not in sys.path:
    sys.path.append(str(Path(__file__).parent))

from descriptor import (
    DescriptorError,
    RunStep,
    load_operations,
    load_procedures,
)

SSH_TIMEOUT_SECONDS = int(os.environ.get("VERIFY_SSH_TIMEOUT", "120"))
"""How long one host may take before it counts as unreachable.

Two minutes, and it was thirty seconds. Measured on a beamline host
while its station was writing a terabyte scan: a bare `ssh host echo ok`
took 53 seconds and the probe this runs took 16. So the old bound
reported a working host as unreachable, and did it under load, which is
when somebody is most likely to be asking whether the fleet is sound.

Unreachable is also the one answer here that cannot be told from the
truth by reading harder, so a bound that produces it wrongly is worse
than a check that takes its time.

Overridable because two minutes is this facility's number rather than a
fact, and a site whose hosts answer at once should not wait it out to
learn a machine is genuinely gone.
"""

_REVISION = re.compile(r"^revision ([a-f0-9]{7,40})", re.M)
_WRITABLE = re.compile(r"^writable\s*=\s*(\[[^\]]*\])", re.M)
_HEADER = re.compile(r"^\[\[?\s*([A-Za-z0-9_.-]+)\s*\]\]?")
_KEY = re.compile(r'^(profile|prefix|routines)\s*=\s*(\[[^\]]*\]|"[^"]*")')

ENVIRON_NAMES: tuple[str, ...] = (
    "EPICS_CA_ADDR_LIST",
    "EPICS_CA_AUTO_ADDR_LIST",
    "EPICS_CA_SERVER_PORT",
    "CORA_TRANSFER_SOURCE",
    "CORA_TRANSFER_DESTINATION",
    "CORA_TRANSFER_PREFIX",
    "CORA_RETRIEVE_SOURCE",
    "CORA_RETRIEVE_DESTINATION",
    "CORA_RETRIEVE_PREFIX",
    "CORA_COMPUTE_ENDPOINT",
    "CORA_COMPUTE_PROJECT",
    "CORA_COMPUTE_QUEUE",
)
"""What is read out of the running conductor's environment, and nothing else.

Read from the process rather than from the files that feed it, because the
two differ exactly where it matters: a unit installed before its
environment file existed carries no line for it, and a shell on the same
host carries the facility's list rather than the unit's. Which address list
a conductor searches with, and which collections its transfer engines were
built against, are both facts only the process holds.

An allow-list rather than a filter, so a variable added to a unit later is
not read until somebody decides it may be. None of these is a credential,
which the transfer profile's own page says of its variables.
"""


@dataclass
class Unit:
    """One service in the account's shared unit directory."""

    name: str
    enabled: str
    active: str
    condition: str


@dataclass(frozen=True)
class Engine:
    """One run table in a conductor's configuration, as the probe read it.

    A scan engine names a `prefix` and a profile engine names a `profile`,
    and either may serve several routines. A conductor that moves data
    holds several of these, one per direction and one for the scan.
    """

    profile: str
    prefix: str
    routines: tuple[str, ...]


@dataclass(frozen=True)
class KeeperReach:
    """Whether the keeper a conductor is configured with answers from its host.

    Asked from the conductor's host because that is where it matters: a
    keeper a laptop cannot reach may be one every beamline reaches, and a
    keeper that is down is refused from everywhere at once. Its certificate
    is not checked, since the only question is whether anything answers.
    """

    url: str
    exit: int
    said: str

    @property
    def status(self) -> str:
        """The HTTP status the keeper returned, or empty when nothing answered."""
        tail = self.said.strip()[-3:]
        return tail if tail.isdigit() and tail != "000" else ""

    @property
    def answers(self) -> bool:
        return self.exit == 0 and self.status.startswith("2")

    @property
    def reason(self) -> str:
        """What the keeper did, worded to follow "the keeper"."""
        if self.answers:
            return "answers"
        if "refused" in self.said.lower():
            return "refuses the connection"
        if self.exit == 28:
            return "does not answer within ten seconds"
        if self.exit == 6:
            return "has a name that does not resolve"
        if self.exit == 0:
            return f"answers with HTTP {self.status or 'nothing'}"
        message = self.said.strip()
        if message[-3:].isdigit():
            message = message[:-3].strip()
        return f"cannot be reached: {message or f'curl exit {self.exit}'}"


@dataclass
class HostReport:
    """What one host disagrees about, and what it could not be asked.

    The fields after `unreachable` are what the host said rather than what
    it disagrees about, kept so that a reader showing the host need not ask
    it a second time.
    """

    beamline: str
    target: str
    revisions: dict[str, str] = field(default_factory=dict[str, str])
    problems: list[str] = field(default_factory=list[str])
    unreachable: str | None = None
    units: list[Unit] = field(default_factory=list[Unit])
    engines: list[Engine] = field(default_factory=list[Engine])
    writable: list[str] = field(default_factory=list[str])
    environ: dict[str, str] = field(default_factory=dict[str, str])
    keeper: KeeperReach | None = None
    errors: int | None = None
    last_error: str = ""
    uptime: int | None = None
    simulated: str = ""

    @property
    def total(self) -> int:
        return len(self.problems) + (1 if self.unreachable else 0)


def ask(
    target: str, script: str, ssh_opts: list[str], timeout: float | None = None
) -> tuple[int, str]:
    """Run one script on a host through bash, whatever its login shell is.

    Through `bash -s` because one beamline account logs in to tcsh, where
    a bare command's quoting does not survive. A deploy script learned
    this twice; there is no reason for this one to learn it again.

    When ssh itself fails, the last line of what it said is appended to
    the output, because that line is the reason: a key the agent does
    not hold and a host that is not there both arrive as exit 255 with
    nothing on standard output, and only ssh's own words tell them apart.
    """
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", *ssh_opts, target, "bash -s"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout or SSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{exc}"
    said = [line for line in done.stderr.splitlines() if line.strip()]
    if done.returncode != 0 and said:
        tail = said[-1].strip()
        return done.returncode, done.stdout + ("" if done.stdout.endswith("\n") else "\n") + tail
    return done.returncode, done.stdout


HOST_PROBE = """
echo "== host.uptime"
cut -d" " -f1 /proc/uptime 2>/dev/null
"""
"""How long the host has been up, so a host that is down reads apart from its services."""

UNITS_PROBE = """
echo "== units"
for f in "$HOME"/.config/systemd/user/cora-*.service; do
  [ -e "$f" ] || continue
  u=$(basename "$f")
  printf '%s|%s|%s|%s\n' "$u" \
    "$(systemctl --user is-enabled "$u" 2>/dev/null)" \
    "$(systemctl --user is-active "$u" 2>/dev/null)" \
    "$(sed -n 's/^ConditionHost=//p' "$f" | head -1)"
done
"""
"""The account's units, on their own, for a host that runs no conductor."""

_PROBE = (
    """
C=$HOME/.config/cora
for app in conductor reporter; do
  echo "== $app.revision"
  sed -n 's/^revision //p' "$HOME/cora-$app/REVISION" 2>/dev/null
done
echo "== conductor.config"
grep -E '^\\[|^routines|^writable|^beamline|^prefix|^profile|^token_file|^token |^base_url' \
  "$C/conductor-SLUG.toml" 2>/dev/null
echo "== conductor.environ"
pid=$(systemctl --user show -p MainPID --value cora-conductor.service 2>/dev/null)
if [ -n "$pid" ] && [ "$pid" != 0 ] && [ -r "/proc/$pid/environ" ]; then
  tr '\\0' '\\n' < "/proc/$pid/environ" | grep -E '^(NAMES)='
fi
echo "== keeper.reach"
url=$(sed -n 's/^base_url *= *"\\([^"]*\\)".*/\\1/p' "$C/conductor-SLUG.toml" 2>/dev/null | head -1)
if [ -n "$url" ] && command -v curl >/dev/null 2>&1; then
  said=$(curl -sS -k -o /dev/null -w '%{http_code}' --max-time 10 "$url/health" 2>&1)
  rc=$?
  printf '%s|%s|%s\\n' "$url" "$rc" "$(printf '%s' "$said" | tr '\\n' ' ')"
fi
echo "== conductor.errors"
if lines=$(journalctl --user -u cora-conductor.service --since -10min \
    --no-pager -o cat 2>/dev/null); then
  printf '%s\\n' "$lines" | grep -ciE 'error|traceback|refused'
  printf '%s\\n' "$lines" | grep -iE 'error|traceback|refused' | tail -1
else
  echo unreadable
fi
""".replace("NAMES", "|".join(ENVIRON_NAMES))
    + """echo "== sim.prefix"
sed -n 's/.* --prefix \\([^ ]*\\).*/\\1/p' "$HOME/.config/systemd/user/cora-tomoscan-sim.service" \
  2>/dev/null | head -1
"""
    + HOST_PROBE
    + UNITS_PROBE
    + "exit 0\n"
)
"""The probe, which always exits cleanly once it has run.

The exit status of a script is its last command's, and `check` reads a
nonzero one as a host that could not be asked. Ending on `exit 0` keeps a
command added later, such as a `grep` that counts nothing and exits 1,
from turning a host that answered every question into an unreachable one.
"""


def listed(raw: str) -> list[str]:
    """The names in a TOML inline array, without parsing the whole file."""
    return re.findall(r'"([^"]*)"', raw)


def section(output: str, name: str) -> str:
    """One `== name` block of the probe's output."""
    blocks = dict(re.findall(r"^== (\S+)\n((?:(?!^== ).*\n)*)", output, re.M))
    return blocks.get(name, "")


def engines(config: str) -> list[Engine]:
    """Every run table in the probe's view of a configuration, in file order.

    The probe keeps table headers for this. A key read outside any header
    is taken as a run table's too, which is the shape a probe that kept no
    headers produced and the shape an old single-table configuration has.
    """
    tables: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_run = True
    for line in config.splitlines():
        header = _HEADER.match(line)
        if header:
            in_run = header.group(1) == "run"
            current = {} if in_run else None
            if current is not None:
                tables.append(current)
            continue
        key = _KEY.match(line)
        if key is None or not in_run:
            continue
        if current is None:
            current = {}
            tables.append(current)
        name, raw = key.groups()
        current[name] = tuple(listed(raw)) if name == "routines" else raw.strip('"')
    return [
        Engine(
            profile=str(table.get("profile", "")),
            prefix=str(table.get("prefix", "")),
            routines=tuple(table.get("routines", ())),
        )
        for table in tables
    ]


def environ(output: str) -> dict[str, str]:
    """The conductor's environment block, narrowed to `ENVIRON_NAMES` again.

    The probe already narrows it on the host. Doing it twice costs nothing
    and means a probe edited carelessly still cannot carry a credential
    into a report.
    """
    found: dict[str, str] = {}
    for line in section(output, "conductor.environ").splitlines():
        name, separator, value = line.partition("=")
        if separator and name in ENVIRON_NAMES:
            found[name] = value
    return found


def keeper_reach(output: str) -> KeeperReach | None:
    """The keeper block of the probe's output, or None when nothing was asked.

    Nothing is asked when the configuration names no keeper or the host
    has no curl, and neither of those is an answer about the keeper.
    """
    for line in section(output, "keeper.reach").splitlines():
        url, first, rest = line.partition("|")
        code, second, said = rest.partition("|")
        if first and second and code.strip().isdigit():
            return KeeperReach(url=url.strip(), exit=int(code), said=said.strip())
    return None


def recent_errors(output: str) -> tuple[int | None, str]:
    """How many errors the conductor logged in ten minutes, and the last one.

    None when the journal could not be read, which is not the same as a
    quiet one and must not be shown as zero.
    """
    lines = section(output, "conductor.errors").splitlines()
    if not lines or not lines[0].strip().isdigit():
        return None, ""
    last = lines[1].strip() if len(lines) > 1 else ""
    return int(lines[0].strip()), last


def host_uptime(output: str) -> int | None:
    """Seconds the host has been up, or None when it was not read."""
    first = section(output, "host.uptime").strip().split(".")[0]
    return int(first) if first.isdigit() else None


def sim_prefix(output: str) -> str:
    """The prefix this account's TomoScan simulator serves, or empty without one.

    Read from the simulator's own unit, where its installer wrote it,
    because a naming habit is not a rule: nothing forces a simulator's
    prefix to look like one.
    """
    return section(output, "sim.prefix").strip()


def units(output: str) -> list[Unit]:
    """The unit block of the probe's output, one record per line."""
    found: list[Unit] = []
    for line in section(output, "units").splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        name, enabled, active, condition = (part.strip() for part in parts)
        found.append(Unit(name=name, enabled=enabled, active=active, condition=condition))
    return found


def arming(found: list[Unit]) -> list[str]:
    """What about this account's arming a reboot would not restore.

    Enablement is one symlink in a directory every host in the account
    mounts, so this is an account-wide answer and the host it was read
    from does not appear in it.
    """
    problems: list[str] = []
    if not found:
        problems.append("the account holds no cora unit files, so a reboot restores nothing here")
    for unit in found:
        if unit.enabled != "enabled":
            running = ", and it is running now" if unit.active == "active" else ""
            problems.append(
                f"{unit.name} is {unit.enabled!r} rather than enabled, so a reboot of "
                f"whichever host runs it does not bring it back{running}"
            )
        if not unit.condition:
            problems.append(
                f"{unit.name} carries no ConditionHost, so every lingering host in this "
                f"account starts its own copy"
            )
    return problems


def check(
    beamline: str, target: str, tree: Path, ssh_opts: list[str], expected_revision: str | None
) -> HostReport:
    report = HostReport(beamline=beamline, target=target)
    code, out = ask(target, _PROBE.replace("SLUG", beamline), ssh_opts)
    if code != 0 or "== conductor.config" not in out:
        report.unreachable = out.strip().splitlines()[-1] if out.strip() else "no answer"
        return report

    for app in ("conductor", "reporter"):
        found = section(out, f"{app}.revision").strip()
        report.revisions[app] = found or "unnamed"
        if not found:
            report.problems.append(f"{app} carries no REVISION, so what it runs cannot be named")
        elif expected_revision and not expected_revision.startswith(found[:40]):
            report.problems.append(
                f"{app} is at {found[:7]}, and the tree is at {expected_revision[:7]}"
            )

    config = section(out, "conductor.config")
    if "token = " in config:
        report.problems.append(
            "the conductor configuration still holds an inline token, so the file is "
            "itself a credential"
        )

    report.engines = engines(config)
    report.environ = environ(out)
    report.units = units(out)
    report.keeper = keeper_reach(out)
    report.uptime = host_uptime(out)
    report.simulated = sim_prefix(out)
    report.errors, report.last_error = recent_errors(out)
    if report.keeper is not None and not report.keeper.answers:
        report.problems.append(
            f"the keeper this conductor is configured with {report.keeper.reason} "
            "from this host, so the conductor can take no work"
        )

    operations = {entry.name for entry in load_operations(tree / "operations.toml").operations}
    named = [routine for engine in report.engines for routine in engine.routines]
    if not named:
        report.problems.append("the conductor configuration names no routines")
    for routine in named:
        if routine not in operations:
            report.problems.append(
                f"run.routines holds {routine!r}, which beamlines/operations.toml "
                f"does not declare. Every dispatch here is refused"
            )

    report.problems.extend(arming(report.units))

    writable = _WRITABLE.search(config)
    fence = listed(writable.group(1)) if writable else []
    report.writable = fence
    prefix = next((engine.prefix for engine in report.engines if engine.prefix), "")
    register = load_procedures(tree / beamline / "procedures.toml")
    for procedure in register.procedures:
        if not procedure.confirmed:
            continue
        for step in procedure.steps:
            if isinstance(step, RunStep):
                report.problems.extend(claimed_elsewhere(procedure.name, step, prefix))
            elif not any(step.record.startswith(allowed) for allowed in fence):
                report.problems.append(
                    f"{procedure.name!r} sets {step.record!r}, which control.writable "
                    f"{fence} does not cover. That step is refused"
                )
    return report


def claimed_elsewhere(name: str, step: RunStep, prefix: str) -> list[str]:
    """Whether a run step's claim describes the hardware its engine drives.

    What a mismatch costs depends on what the host is running, and this
    cannot tell from here without pinning a revision, so it names both.

    A conductor carrying the station fence declines the step. Nothing
    runs and nothing is endangered, and the beamline cannot dispatch
    that procedure at all. Where it is the only confirmed one, that is
    a station with no routine, which is safe and is not working.

    A conductor without it compares the two nowhere. The step takes a
    claim on a namespace nobody is serving, drives the prefix, and
    reports success, and the record reads as the thing it claimed.

    Neither is an outcome to leave, and the fix is the same for both:
    the register is wrong, not the deployment. This said the step was
    refused before anything refused it, and then went on saying it was
    not refused after something did, which is the hazard of a message
    that states a consequence rather than the disagreement.

    A step that drives no device is skipped rather than measured. Its
    work happens at another facility, so there is no prefix for its
    claim to agree with and it declares no scopes to compare.
    """
    if step.drives_no_device:
        return []
    if not prefix:
        return [
            f"{name!r} claims {list(step.scopes)} and the conductor names no "
            "run.prefix, so what its scan would drive cannot be read from here"
        ]
    stray = [scope for scope in step.scopes if not scope.startswith(_station(prefix))]
    if not stray:
        return []
    return [
        f"{name!r} is confirmed and claims {stray}, while this conductor drives "
        f"{prefix!r}. A conductor with the station fence declines that step, so "
        "the beamline cannot dispatch this procedure; one without it drives the "
        "prefix anyway and reports success. Correct the register, not the host"
    ]


def _station(prefix: str) -> str:
    """The part of an engine prefix a claim at the same station would share.

    `19bm:TomoScan:` is served by the station that serves `19bm:det:`, so
    the comparison is against `19bm:` rather than against the whole
    prefix. Taking the whole prefix would report every honest claim at
    the beamline, because no procedure claims the scan server itself.
    """
    head, separator, _ = prefix.partition(":")
    return head + separator if separator else prefix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", required=True, metavar="SLUG=TARGET")
    parser.add_argument("--tree", type=Path, default=Path(__file__).parent)
    parser.add_argument("--ssh-opts", default="")
    parser.add_argument("--revision", default=None, help="the commit every host should be at")
    args = parser.parse_args(argv)

    ssh_opts = args.ssh_opts.split()
    reports: list[HostReport] = []
    for pair in args.host:
        if "=" not in pair:
            print(f"error: --host wants SLUG=TARGET, got {pair!r}", file=sys.stderr)
            return 2
        beamline, target = pair.split("=", 1)
        try:
            reports.append(check(beamline, target, args.tree, ssh_opts, args.revision))
        except DescriptorError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    for report in reports:
        if report.unreachable:
            print(f"{report.beamline}: could not be asked, {report.unreachable}")
            continue
        shipped = " ".join(f"{app} {sha[:7]}" for app, sha in report.revisions.items())
        if not report.problems:
            print(f"{report.beamline}: agrees, {shipped}")
            continue
        print(f"{report.beamline}: {len(report.problems)} disagreement(s), {shipped}")
        for problem in report.problems:
            print(f"    {problem}")

    agreed = {sha for r in reports for sha in r.revisions.values()}
    if len(agreed) > 1:
        print(
            f"\nthe fleet is on {len(agreed)} revisions: {', '.join(sorted(s[:7] for s in agreed))}"
        )

    total = sum(report.total for report in reports)
    print(f"\n{total} disagreement(s) across {len(reports)} host(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
