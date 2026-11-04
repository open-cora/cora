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
A conductor running the Globus transfer engine needs `--extra transfer` as
well, for the SDK and the token store that profile imports.

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

`PROFILE_PATH` defaults to `../transferring` under the app, which is where
this repository ships the Globus transfer engine. A deployment with its own
points it elsewhere.

Write `[[run]]` for each one. A beamline that acquires and then moves what
it acquired names both:

```toml
[[run]]
prefix = "19bmTomoScan:"
routines = ["tomography_scan"]

[[run]]
profile = "transfers:engine"
routines = ["transfer"]
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
the two engines cannot run in the same place: a transfer engine needs
network egress and a credential, an acquisition engine needs Channel
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
