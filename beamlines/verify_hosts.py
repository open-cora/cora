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

Read-only. It runs `ssh` and reads three things per host, and writes
nothing anywhere.

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

This file used to report such a row as "that step is refused", which was
the comfortable reading and the wrong one. A reader who saw it would
conclude the system was already stopping the thing it was in fact
running.

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

sys.path.insert(0, str(Path(__file__).parent))

from descriptor import DescriptorError, RunStep, load_operations, load_procedures

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
_ROUTINES = re.compile(r"^routines\s*=\s*(\[[^\]]*\])", re.M)
_WRITABLE = re.compile(r"^writable\s*=\s*(\[[^\]]*\])", re.M)
_PREFIX = re.compile(r'^prefix\s*=\s*"([^"]*)"', re.M)


@dataclass
class Unit:
    """One service in the account's shared unit directory."""

    name: str
    enabled: str
    active: str
    condition: str


@dataclass
class HostReport:
    """What one host disagrees about, and what it could not be asked."""

    beamline: str
    target: str
    revisions: dict[str, str] = field(default_factory=dict[str, str])
    problems: list[str] = field(default_factory=list[str])
    unreachable: str | None = None

    @property
    def total(self) -> int:
        return len(self.problems) + (1 if self.unreachable else 0)


def ask(target: str, script: str, ssh_opts: list[str]) -> tuple[int, str]:
    """Run one script on a host through bash, whatever its login shell is.

    Through `bash -s` because one beamline account logs in to tcsh, where
    a bare command's quoting does not survive. A deploy script learned
    this twice; there is no reason for this one to learn it again.
    """
    try:
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", *ssh_opts, target, "bash -s"],
            input=script,
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{exc}"
    return done.returncode, done.stdout


_PROBE = """
C=$HOME/.config/cora
for app in conductor reporter; do
  echo "== $app.revision"
  sed -n 's/^revision //p' "$HOME/cora-$app/REVISION" 2>/dev/null
done
echo "== conductor.config"
grep -E '^routines|^writable|^beamline|^prefix|^token_file|^token ' \
  "$C/conductor-SLUG.toml" 2>/dev/null
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


def listed(raw: str) -> list[str]:
    """The names in a TOML inline array, without parsing the whole file."""
    return re.findall(r'"([^"]*)"', raw)


def section(output: str, name: str) -> str:
    """One `== name` block of the probe's output."""
    blocks = dict(re.findall(r"^== (\S+)\n((?:(?!^== ).*\n)*)", output, re.M))
    return blocks.get(name, "")


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

    operations = {entry.name for entry in load_operations(tree / "operations.toml").operations}
    routines = _ROUTINES.search(config)
    if routines is None:
        report.problems.append("the conductor configuration names no routines")
    else:
        for routine in listed(routines.group(1)):
            if routine not in operations:
                report.problems.append(
                    f"run.routines holds {routine!r}, which beamlines/operations.toml "
                    f"does not declare. Every dispatch here is refused"
                )

    report.problems.extend(arming(units(out)))

    writable = _WRITABLE.search(config)
    fence = listed(writable.group(1)) if writable else []
    prefix_found = _PREFIX.search(config)
    prefix = prefix_found.group(1) if prefix_found else ""
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

    Not a refusal anywhere. A run step's scopes are compared to nothing
    at runtime, so a mismatch is work that happens on the prefix while
    the record says it happened somewhere else, which is the reason this
    is reported as sharply as it is.

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
        f"{prefix!r}. A run step's scopes are never compared to the engine, so "
        "this is not refused: the claim protects nothing and the scan is real"
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
