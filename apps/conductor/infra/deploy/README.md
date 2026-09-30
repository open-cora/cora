# Deploying a conductor

One conductor per beamline, supervised by `systemd --user`, with no root and
no system package.

```bash
BEAMLINE=7-bm ./install.sh
```

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

The installer builds the virtualenv when there is none, and `SYNC=1` forces
a rebuild. That needs a package index. **A beamline whose conductor host
cannot reach one builds it on a machine that can and shares it through the
beamline's home**, which is what the shared home is for. Build on the older
platform when the two differ: a wheel built against a newer C library will
not load against an older one, and the reverse is fine.

## ConditionHost is not decoration

`systemd --user` reads units only from `$HOME`, and a beamline's `$HOME` is
NFS mounted by every machine at that beamline. Without the guard, enabling
this once from the wrong shell starts a **second conductor at the same
beamline, asking for the same work**. Two conductors claiming one beamline
is the conflict the claim ledger exists to arbitrate, and it is not worth
causing on purpose. The installer writes whatever `hostname` returns,
because the spelling is not uniform across these machines.

## No engine

There is no `run` table in the configuration, so no engine is loaded. A
procedure made only of record sets runs without one. A procedure naming a
run is refused when it is reached, rather than at startup, so a beamline
that never uses one never notices. That is deliberate, not unfinished.

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
tail -f ~/.config/cora/conductor-<beamline>.log
```

`Restart=always` with a fifteen second interval, long enough that a
misconfiguration does not become a request flood at the keeper. A conductor
that stops is a beamline that silently accepts no work: the keeper holds the
execution and waits, and nothing else notices.
