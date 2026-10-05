# Deploying the thinker

One thinker for the whole facility, supervised by `systemd --user`, with no
root and no system package.

```bash
./install.sh
```

Re-running it deploys a new revision. It restarts the service rather than
relying on `enable --now`, which is a no-op against something already
running and would leave a changed unit on disk that never reaches the
process.

## Why there is no beamline here

Every sibling installer takes one and this takes none. A thinker asks the
keeper for any question nobody has taken up, and an inquiry names an
execution rather than a beamline, so where the work ran is read off the
record rather than configured. There is nothing to tell it, and nothing a
second installation would divide.

Two thinkers running at once is allowed and settled by the claim, which
makes a duplicate harmless rather than correct: both reach for one
question, one loses, and the loser has spent an ask. The unit carries a
`ConditionHost` anyway, because on a shared home a unit enabled from the
wrong shell starts one somewhere nobody is looking.

## Where it runs

Wherever its thinking is. That is the only thing holding it: it needs
network access to the keeper and to whatever concludes, and nothing else,
no database, no queue, no inbound port.

With the deterministic profile this repository ships, nothing pins it at
all, so it goes on the host the keeper is on and reaches it without
leaving the machine. With local weights it goes to the cards, and this
page stops being the one that decides.

## What it needs first, and does not create

**A configuration file at `~/.config/cora/thinker.toml`, mode 600.** It
carries the bearer token, and minting and distributing those belongs to
whoever runs the keeper. A script that could write this one could write one
for any caller. The installer refuses to proceed if the file is missing or
readable by anyone else.

```toml
[keeper]
base_url = "https://localhost:8443"
token = "the thinker's token"

[inference]
profile = "baseline:inference"
```

**A CA bundle at `~/.config/cora/ca-bundle.crt`**, carrying the system
anchors plus the keeper's own CA. Pointing the client at the bare CA would
work and would also make the process distrust every other endpoint, which
is a surprise waiting for the first one.

**Lingering**, or the service stops the moment nobody is logged in. On
these hosts an account can enable it for itself with `loginctl
enable-linger`, needing no administrator, which is worth trying before
filing a request.

No `epics.env`, unlike the siblings. A thinker never speaks to an engine.

## The thinking, and where it comes from

`inference.profile` names something importable that hands back whatever
concludes. It is a dotted path rather than a block of settings because a
client with its own credentials and state is an object a text file cannot
hold.

This repository ships three under `infra/thinking`, which the installer
puts on the path: one that only advises, one that climbs a parameter
deterministically, and one that asks a model through a gateway. A
deployment that wants different thinking writes its own and points
`PROFILE_PATH` and `inference.profile` at that.

A profile needing settings of its own reads them from `THINKING_ENV`,
which the installer turns into an `EnvironmentFile` when the file exists.
That is where a gateway address, a username and a model name go. They are
not in the thinker's own configuration, which holds what a thinker is
rather than what a model is, and they are not in the unit, which is world
readable in a shared home.

## The virtualenv, and why the package looks empty without it

`thinker` declares no core dependencies on purpose. So a plain `uv sync`
installs one package and the process cannot reach the keeper. It needs
`--extra service` for the HTTP client:

```bash
SYNC=1 ./install.sh
```

which needs a package index. A host that cannot reach one builds the
virtualenv on a machine that can and shares it.

## What the installer proves before it starts anything

A thinker that cannot work does not announce it. It starts, fails, is
restarted, fails again, and looks exactly like a facility where nobody is
asking questions. Both ways that happens are checked first.

**The thinking loads**, through the entrypoint's own loader rather than a
bare import, because the dotted path, the attribute lookup and the call are
what the service depends on.

**The keeper answers and accepts the token**, with one unwaited ask. A
token that is refused produces the same silence as a facility with no
questions in it, and the long poll hides it.

## Settings

| | default | |
| --- | --- | --- |
| `CONFIG` | `~/.config/cora/thinker.toml` | holds the token, mode 600 |
| `CA_BUNDLE` | `~/.config/cora/ca-bundle.crt` | system anchors plus the keeper's CA |
| `PROFILE_PATH` | `../thinking` under the app | what goes on `PYTHONPATH` |
| `THINKING_ENV` | `~/.config/cora/thinking.env` | settings for the profile, if it needs any |
| `WAIT` | `30` | seconds one request may be held open |
| `LOG` | `~/.config/cora/thinker.log` | |
| `SYNC` | unset | `1` builds the virtualenv |

`WAIT` is a bound on the socket rather than on anybody's patience:
connections held open indefinitely die in proxies and NAT tables without
telling either end, and nothing is lost at the ceiling, because a question
sits there until something takes it. The keeper refuses an ask above its
own ceiling of sixty seconds.

## Shipping a revision

```bash
ETC=/local/cora/etc LOG=/local/cora/log/thinker.log HOST=<central-host> ./push.sh HEAD
```

`push.sh` exports a named commit rather than the working tree, writes a
`REVISION` file beside the code, and runs this installer over SSH. It is
byte-identical to the copy the other apps carry, and a test in the
development tree proves they have not drifted.

The code lands in `cora-thinker` under the home, where every other app on
that host lives. The two settings move only what must not sit on NFS: the
home there is mounted by every machine the account can log into, so a
token at mode 600 in it is readable on all of them and the same file on
local disk is readable on one. `LOG` is separate from `ETC` because the
host already keeps logs in one place, and a second convention under `etc`
would split them.

The two do not fail alike when left out. Without `ETC` the installer looks
for a configuration in the home, does not find one, and stops having
written nothing the running service reads. Without `LOG` it succeeds and
rewrites the unit to log somewhere new, which is the one that is quiet
about what it did.
