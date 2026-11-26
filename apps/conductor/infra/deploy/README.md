# Deploying a conductor

One conductor per beamline, supervised by `systemd --user`, with no root
and no system package.

```bash
BEAMLINE=7-bm ./install.sh
```

One, even where the work crosses a boundary. A conductor holds as many
engines as its configuration names and picks between them by the routine
a step asks for, so a beamline that takes data and then moves it writes
two `[[run]]` tables rather than running two services.

Re-running it deploys a new revision. It restarts the service rather than
relying on `enable --now`, which is a no-op against something already
running and would leave a changed unit on disk that never reaches the
process.

## What it needs first, and does not create

**A configuration file at `~/.config/cora/conductor-<beamline>.toml`, mode
600.** It carries the beamline's bearer token, and minting and distributing
those belongs to whoever runs the keeper. A script that could write this one
could write one for any beamline. The installer refuses to proceed if the
file is missing or readable by anyone else.

**A CA bundle at `~/.config/cora/ca-bundle.crt`**, carrying the system
anchors plus the keeper's own CA. Pointing the client at the bare CA would
work and would also make the process distrust every other endpoint, which is
a surprise waiting for the first one.

**Lingering**, or the service stops the moment nobody is logged in. On these
hosts an account can enable it for itself with `loginctl enable-linger`,
needing no administrator, which is worth trying before filing a request.

**An `epics.env`**, only where the conductor cannot find its records by
broadcast. It is picked up automatically when present.

## The virtualenv, and why the package looks empty without it

`conductor` declares no core dependencies on purpose: which control library
a deployment runs is a choice made at its entrypoint. So a plain `uv sync`
installs one package and the process will not start. It needs
`--extra service` for the HTTP client and `--extra epics` for Channel
Access, and the installer checks both are importable before it will finish.
A conductor running the mover or the processor also needs `--extra
transfer` and `--extra compute`, for the SDKs and the token store those
profiles import, and the installer adds both when a profile is named.

The installer builds the virtualenv when there is none, and `SYNC=1` forces
a rebuild. That needs a package index. **A beamline whose conductor host
cannot reach one builds it on a machine that can and shares it through the
beamline's home**, which is what the shared home is for. Build on the older
platform when the two differ: a wheel built against a newer C library will
not load against an older one, and the reverse is fine.

## ConditionHost is not decoration

`systemd --user` reads units only from `$HOME`, and a beamline's `$HOME` is
NFS mounted by every machine at that beamline. Without the guard, enabling
this once from the wrong shell starts a **second copy of this conductor on
another machine, asking for the same work**. Two conductors asking for the
same work is the conflict the claim ledger exists to arbitrate, and it is
not worth causing on purpose. The installer writes whatever `hostname`
returns, because the spelling is not uniform across these machines.

## Which engines, and the three arrangements

A conductor's run tables say what it can be asked for. Each one is an
engine, each engine names its routines, and two engines may not offer the
same routine: that is refused at startup rather than resolved by order.

**No `run` table.** No engine is loaded. A procedure made only of record
sets runs without one. A procedure naming a run is refused when it is
reached, rather than at startup, so a beamline that never uses one never
notices. That is deliberate, not unfinished.

**`run.prefix`.** A scan server at a record prefix. Everything the engine
takes is a string, so the file says it and the deployment writes no code.

**`run.profile`.** An engine the deployment builds, named `module:attribute`.
The installer puts `PROFILE_PATH` on the unit's `PYTHONPATH` so the module
imports, and checks before installing that it does: a profile that will not
import would otherwise start, fail, and be restarted forever while looking
like a beamline nobody dispatches to.

`PROFILE_PATH` defaults to `infra/transferring` and `infra/computing` under
the app, which is where this repository ships the mover and the
processor. A deployment with its own points it elsewhere.

Write `[[run]]` for each one. A beamline that acquires and then moves what
it acquired names both:

```toml
[[run]]
prefix = "19bmTomoScan:"
routines = ["tomography_scan"]

[[run]]
profile = "transfers:mover"
routines = ["move"]
```

`[run]` as a single table still parses and means one engine, so nothing a
beamline has already written needs changing.

Whatever a profile is configured with goes in **`run-<beamline>.env`**,
read as an `EnvironmentFile`, not in the configuration beside the token.
Those settings belong to the engine rather than to the conductor, and the
file is optional: a profile that needs none runs without it.
[../transferring/README.md](../transferring/README.md) lists what the
shipped one reads.

## When a beamline does need two conductors, and what INSTANCE is for

Not for holding two engines, which one conductor does. For the case where
the two engines cannot run in the same place: the mover and the processor
need network egress and a credential, an acquisition engine needs Channel
Access to the station, and at this facility no machine was measured to
find an IOC by broadcast and reach the internet both. Where a pinned
`EPICS_CA_ADDR_LIST` does not bridge that, the engines go on two hosts.

Two conductors at one beamline do not race. A conductor sends the routines
it runs and the keeper answers with the executions whose **every** routine
is in that set, so conductors holding different engines are offered
disjoint work. What collides is the names, because the unit and the
configuration live in a `$HOME` that every machine at the beamline mounts,
so there is one of each per beamline and not per host. `INSTANCE` suffixes
them:

| without | with `INSTANCE=transfer` |
| --- | --- |
| `cora-conductor.service` | `cora-conductor-transfer.service` |
| `conductor-19-bm.toml` | `conductor-19-bm-transfer.toml` |
| `run-19-bm.env` | `run-19-bm-transfer.env` |

It may hold only lowercase letters, digits and hyphens, because it becomes
part of a filename and part of a unit name.

The cost is that a procedure cannot span them. Neither conductor runs
every routine in a procedure naming both a scan and a transfer, so it
matches neither and waits forever. Split that way, chaining is a matter of
separate executions, which is what a pursuit opens. One conductor with two
engines keeps it to one procedure, which is why it is the default.

## What the installer checks, and why active is not enough

A conductor that cannot reach the keeper stays active and retries, which
from systemd looks exactly like a healthy idle one. So finishing requires
three things, not one: the service is active, the log says it asked the
keeper for work at this beamline, and nothing in the recent log reads as a
failure. Any of those missing is an error rather than a warning.

## After a reboot

**Enabled, pinned and lingering is not enough on these hosts.** The unit
lives in the beamline's NFS home, and a lingering user manager starts at boot
whether or not that home is mounted yet. One that starts first finds no unit,
starts nothing, and never looks again. That left every service on the central
host down for two weeks once, until a reload and a start were typed by hand.
It has not been seen at a beamline, but the homes there are the same kind and
run with linger, so the installer does not wait to find out.

### What the installer arms

`install.sh` writes one line into the account's crontab on this host:

```
*/5 * * * * /bin/bash <app>/infra/deploy/after-boot.sh run cora-conductor-after-boot cora-conductor.service=<app>/infra/deploy/nothing-is-waiting.sh # cora-conductor-after-boot
```

The crontab sits in the host's own spool on local disk, so the line exists on
this host and nowhere else. Every five minutes `after-boot.sh` starts a
conductor that is enabled, pinned to this host, and has not begun to start
since the manager came up, after telling the manager to reload if it never
read the file, and only once the guard lets it. A conductor somebody stopped
or disabled is left alone. A tick with nothing to do writes nothing; one that
acts says so in the journal:

```bash
journalctl --user -t cora-conductor-after-boot
```

The account can read those lines only where the journal is persistent, which
means `/var/log/journal` exists on the host.

The line names every conductor pinned to this host, not only the one being
installed. A host running an instance beside the default carries one line
naming both, and re-running either installer re-arms both, where a line armed
per install under one name would have each install write the other off. The
account is shared with the beamline, so that crontab may hold other people's
jobs: arming replaces this job's own line and leaves every other line as it
was.

The installer refuses before it changes anything if the host has no cron
running, no `flock`, or does not let the account use cron. On a host with an
`/etc/cron.allow`, that permission is an administrator's to give.

### Why a conductor carries a guard

A conductor asks for work the moment it starts, and takes whatever was
dispatched to its beamline and never taken up the moment it is answered. The
job brings it back with nobody deciding, on the first tick after the home is
back: minutes after the boot when the mount was merely late, and as long as
the outage when the home itself was gone. Before the job, a conductor in that
state stayed down until a person noticed, and that person was the decision.
With it and no guard, work dispatched in the meantime, a scan for a sample
long since unloaded or in somebody else's beamtime, would start moving the
station the moment the home returned.

The keeper's own guard does not reach this. It holds the keeper's API while
anything is queued, which covers a keeper coming back to conductors that kept
asking. A beamline host that reboots while the keeper stays up is the other
order, and the conductor is the one coming back.

So each conductor on the line carries `nothing-is-waiting.sh`. The job hands
it the unit's name. It reads the interpreter, the configuration and the
certificate bundle out of that unit and asks the keeper, with the conductor's
own token, for what is dispatched to its beamline and not yet taken up. It
reads and never claims, and it answers the way the keeper's guard does:

| exit | means | what the job does |
| --- | --- | --- |
| 0 | nothing is waiting | starts the conductor |
| 1 | something is | holds it, and the journal lists each execution |
| 2 | the queue could not be read | holds it as well |

It narrows by beamline and not by the routines the conductor runs. Work sent
to this station that nothing here can run is still work somebody sent to this
station, and whether it should run is the same decision.

The installer runs the guard once, after the conductor is up, and refuses on a
2: a guard that cannot read the queue would hold the conductor after every
boot the job acts on.

**Releasing a hold.** The job asks again at every tick, so a hold ends by
itself once nothing is waiting:

1. If the work should not run, end each execution the journal names, with
   this beamline's token: `POST /executions/<id>/end`. The next tick starts
   the conductor.
2. If it should run, start the conductor by hand:
   `systemctl --user start cora-conductor.service`. The guard holds only the
   job; a person starting the unit is not asked, because a person is the
   decision it was waiting for.

**What the guard does not cover.** It holds a conductor only on a boot where
the manager missed the unit, because that is the only boot the job acts on. A
boot that finds the home in time starts the conductor itself, unguarded, as it
always has. So does `Restart=always` after a crash, and so does this
installer, which restarts the conductor into whatever is waiting. Holding
every return would mean deciding, in the keeper or in the conductor, what work
is too old to take, which is a separate change.

### Checking it without a reboot

```bash
crontab -l | grep cora-conductor-after-boot
ls -l --time-style=+%T "/run/user/$(id -u)/cora-conductor-after-boot.lock"
./nothing-is-waiting.sh cora-conductor.service; echo "exit $?"
```

The first shows the line. The second changes every five minutes, because each
tick that finds a manager opens it; cron's own log belongs to root on a stock
install, so this is how the account itself sees that cron runs the job. The
third is the guard by hand, read only, with the exit codes the job reads.

Moving a conductor to another host leaves the old host's line behind. It does
nothing there, because the unit is pinned to the new host, and `crontab -e` on
the old host removes it.

### The other units this project installs

The turner, the citation records and the two simulators arm the same job
from their own installers, each under its unit's name with `-after-boot` in
place of `.service`, through the `after-boot.sh` in this directory. Only the
turner's waits on a guard: `../turner/no-pursuit-is-running.sh` holds it while
any pursuit is running, because a turner that comes back dispatches the next
step of every pursuit at once, however long it was away. The other three come
back bare, because what could go wrong on their return is a second server for
a name, which is as likely when a boot starts them as when the job does, and
the check against that is in their units instead.

## The soft IOCs refuse a second server

The citation records and the two simulators serve records under names a
station may also serve: the citation records under the station's own
prefix, deliberately, and the simulators under prefixes of this system's
own that nothing else should hold. Two servers answering one name is a race
whose loser is silent. Each installer refuses when a name already answers,
but an installer runs once, and a unit is started again by every boot,
every restart and the after-boot job.

So each of those units starts through `serve-alone.sh` in this directory,
with the server after its `--`. Before every start it asks whether the
control record answers and whether any of the unit's names already does,
which is the installer's own preflight asked again:

| it finds | exit | what systemd does |
| --- | --- | --- |
| the control answers and no name does | becomes the server | runs it |
| a name already answers | 78 | leaves the unit failed, because the unit names 78 in `RestartPreventExitStatus` |
| the control is silent, or `caget` is not there yet | 75 | tries again fifteen seconds later |

A silent control is not a refusal: an absent record and an unreachable
station fail identically, and at a boot it is usually the station's own IOC
not being up yet. A refusal is not retried, because asking again every
fifteen seconds would only refuse again and bury the reason.

It asks with the `caget` and the `EPICS_CA_` settings the installer ran
under, which the installer writes beside the unit's log as
`<service>-<beamline>.client.env` once its preflight has shown they can see
the station. The user manager's environment is not that shell's, and what
the unit itself sets is the server's: a port a client would read as the one
to search on. Running the installer again rewrites the file.

A refusal names the record that answered, in the unit's log and in
`systemctl --user status`. Find what serves it with `cainfo`. If the
station's own database has gained the citation records, that unit has done
its job and `systemctl --user disable --now cora-citation-ioc.service` ends
it. Otherwise stop whatever else answers, and `systemctl --user start` is
the retry.

## Operating it

```bash
systemctl --user status cora-conductor.service
journalctl --user -u cora-conductor.service -f
```

An instance answers to its own name, so a host running two is read one at a
time:

```bash
journalctl --user -u cora-conductor-transfer.service -f
```

`Restart=always` with a fifteen second interval, long enough that a
misconfiguration does not become a request flood at the keeper. A conductor
that stops is a beamline that silently accepts no work: the keeper holds the
execution and waits, and nothing else notices.
