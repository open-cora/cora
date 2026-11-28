# Deploying the keeper

Installs the keeper and its database as `systemd --user` services, with no
root, no system package and no Docker.

```bash
CORA_ROOT=/local/cora ./install.sh
```

Re-running it is the intended way to deploy a new revision. It never
regenerates a password that exists and never touches an initialised data
directory.

## What decides the shape of this

Three properties of the host, each measured rather than assumed, and each
responsible for a choice that would otherwise look arbitrary.

**There is no root.** Supervision is `systemd --user`, which stops every
service at logout unless lingering is enabled for the account. An
administrator has to run `loginctl enable-linger <account>` once; nothing
here can.

**There is no Docker, and podman is rootless.** Rootless podman needs a
`subuid` and `subgid` range for the account, or an image cannot map its own
internal users and Postgres fails during initdb. The range is keyed by
numeric uid in `/etc/subuid`, not by name, which is worth knowing before
concluding an account has none.

**`$HOME` is NFS and shared.** Every machine the account can log into mounts
it, so a unit file written here is visible on all of them. Each unit
therefore carries `ConditionHost`, and `install.sh` fills it from the host's
own `hostname` because the spelling is not uniform: some machines answer with
a fully qualified name and some with a short one, and systemd compares
against whichever the host gives.

Everything with state lives on local disk for the same reason inverted.
Postgres over NFS is a file-locking hazard even with one writer, and two
hosts reaching one cluster is data loss rather than a warning.

## Why plain units and not quadlet

Quadlet is the better tool and this deployment cannot use it. It always
passes `--cgroups=split`, which requires cgroups v2. A host on v1 cannot
create a cgroup for a rootless container, so podman exits 126 with a
permission error against `/sys/fs/cgroup` before the image starts. A plain
unit passes no cgroup flag and runs.

The failure is worth recognising because it looks like a podman problem and
is a kernel one. Check with `stat -fc %T /sys/fs/cgroup`, and prefer a
`.container` file on any host that reports `cgroup2fs`.

## Who a caller is

`issue_tokens.py` mints an EC signing key, writes the public half as a JWKS,
and signs one long-lived bearer token per caller. `install.sh` runs it, sets
`REQUIRE_AUTHENTICATED_PRINCIPAL`, and serves the JWKS on loopback for the
keeper's own verifier to fetch. The `X-Principal-Id` header stops being
believed at that point.

This is not an identity provider. There is no discovery document, no token
endpoint, no refresh and no revocation. It is enough because the roster is
four beamlines and a thinker, known in advance, and because the verifier
asks only for a JWKS and a signature. Revoking means re-minting the key and
reissuing five files.

**Each token goes to exactly one caller**, into that account's own home at
mode 600, and nothing here should ever be copied to more than one beamline.
The private key never leaves the keeper's host.

### What a subject is called

A subject is `<role>-<beamline>` for anything that runs at a beamline, and
the bare role for anything central. So `conductor-19-bm` and
`reporter-19-bm`, and `thinker` with no suffix. The beamline half is spelled
the way `beamlines/` spells it: `2-bm`, `7-bm`, `19-bm`, `32-id`.

The order is not a preference. That string already names the configuration,
the log and, through `{subject}.token`, the credential itself, so a subject
in the other order would be the one artifact of four spelled differently
from the rest, and an operator holding `reporter-2-bm.toml` would have to
transpose it to find the token.

Splitting a beamline into two subjects buys attribution and nothing else.
It is not a security boundary: both processes run in the same account from
the same home, so whoever can read one token can read the other. There is
no revocation to be granular about either.

**Renaming a subject mints a different principal.** `actor_id` is a `uuid5`
of the subject, so `19-bm` and `conductor-19-bm` are two principals and
everything already recorded stays attributed to the first. Provenance
splits at the rename, which is why it is worth doing once rather than
drifting into it.

`subject_bindings` is a list, so both can be bound at once. The migration
is to add the new subjects, swap each configuration in its own time, and
drop the old ones at a later restart. Nothing is down and there is no flag
day.

**The running keeper predates this.** It binds `2-bm`, `7-bm`, `19-bm`,
`32-id` and `thinker`, one per beamline with no role in the name, so a
beamline's conductor and its reporter share a subject today. That is why
the examples elsewhere in this file still name `2-bm.token`. Changing it
needs a keeper restart, which every beamline feels, so it waits for a
restart that was going to happen anyway.

`install.sh` verifies both directions itself and refuses to finish if an
anonymous request is answered, because a check that only tries the valid
case cannot tell an enforcing deployment from an open one. That exact
mistake shipped an unauthenticated API here once already.

```bash
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  "https://$HOST:8443/devices"
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(cat "$CORA_ROOT/etc/tokens/2-bm.token")" \
  "https://$HOST:8443/devices"
```

401 then 200. `/health` answers without a token on purpose, so a liveness
check needs no credential.

**Authentication says who is calling, the policy says what they may do**, and
the second needs its own negative control for the same reason the first does.
A token that succeeds proves nothing on its own: a deployment with no
`AUTHZ_POLICY_ID` permits every authenticated caller everything, and looks
identical from the outside until something is refused.

```bash
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(cat "$CORA_ROOT/etc/tokens/2-bm.token")" \
  "https://$HOST:8443/events"
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(cat "$CORA_ROOT/etc/tokens/viewer.token")" \
  "https://$HOST:8443/events"
```

403 then 200. A beamline token holds no log read and the viewer's does, so the
pair separates an enforcing deployment from a permissive one in a way either
request alone cannot.

## The wire

`issue_tls.py` mints a small CA and a server certificate for the name
clients dial, and uvicorn terminates TLS itself, so there is no proxy, no
privileged port and no root. **The API is the only thing reachable off the
host.** The database and the JWKS stay on loopback because nothing else
reads them.

There is no plaintext port, deliberately. A token sent in the clear is a
token anyone on the path can lift and replay, so offering both would undo
the reason for having either.

A private CA rather than a public one because the keeper answers on a
facility address with no inbound path from the internet, so an HTTP or DNS
challenge cannot complete, and a search of the host found no internal
issuing service. A CA plus a leaf rather than one self-signed certificate so
that reissuing the server key never means touching every client again.

**Each beamline needs exactly two files**, and no more: its own token, and
`ca.crt` so it can verify the server. Neither is a secret shared with any
other beamline, and the CA private key signs nothing else and never leaves
the keeper's host.

**TLS and the token answer different questions and neither should grow into
the other.** TLS makes the wire private and proves the server; the token
says which beamline is calling. Swapping this CA for a facility one later is
a certificate on the server and a path on each client, and changes no part
of the design.

The certificate expires. 825 days for the leaf, ten years for the CA, and
reissuing the leaf is deleting it and running `install.sh` again.

## What it is not

**No backups.** The database is a bind mount at `$CORA_ROOT/pgdata`, so
`pg_dump` through the container is the whole story for now.

## Operating it

```bash
systemctl --user status cora-keeper.service cora-keeper-postgres.service
journalctl --user -u cora-keeper.service -f
tail -f "$CORA_ROOT/log/keeper.log"
podman logs -f keeper-postgres
```

Deploy a revision by updating the source and running `install.sh` again. It
restarts each service rather than relying on `enable --now`, which is a no-op
against something already running and would otherwise write a new
configuration to disk that never reaches the process.

Starting the database over needs podman, because `:U` chowned the directory
to a subordinate uid the account cannot remove directly:

```bash
systemctl --user stop cora-keeper.service cora-keeper-postgres.service
podman unshare rm -rf "$CORA_ROOT/pgdata"
./install.sh
```

## After a reboot

**Enabled, pinned and lingering is not enough on this host.** The unit files
live in an NFS home, and a lingering user manager starts at boot whether or
not that home is mounted yet. One that starts first finds no unit directory,
starts nothing, and never looks again. `systemctl --user show` then reports an
empty `UnitFileState` and a `ConditionResult` of `no` with no timestamp, while
`is-enabled` still reads `enabled` from the symlink on disk and the journal
holds nothing, because nothing was attempted.

That is how this keeper sat down for two weeks after its host rebooted, and
what brought it back was a reload and a start typed by hand. The late mount is
the explanation that fits and was not measured there. It was reproduced
elsewhere on systemd 239, the release that host ran at the time: a lingering
manager started with the home missing reports exactly those tells once the
home appears, refuses a start until it is told to reload, and stays that way.

### What the installer arms

`install.sh` writes one line into the account's crontab on this host:

```
*/5 * * * * /bin/bash <app>/infra/deploy/after-boot.sh run cora-keeper-after-boot cora-keeper-postgres.service cora-keeper-jwks.service cora-keeper.service=<app>/infra/deploy/nothing-is-queued.sh # cora-keeper-after-boot
```

The crontab sits in the host's own spool on local disk, so the line exists on
this host and nowhere else, and it is the one place the account can start from
without waiting on the home or asking an administrator. Every five minutes
`after-boot.sh` looks at the three units. It starts a unit only when the unit
is enabled, pinned to this host, and has not begun to start since the manager
came up, after telling the manager to reload if it never read the file. A unit
somebody stopped or disabled is left alone. A tick with nothing to do writes
nothing; one that acts says so in the journal:

```bash
journalctl --user -t cora-keeper-after-boot
```

The account can read those lines only where the journal is persistent, which
means `/var/log/journal` exists on the host. A volatile journal keeps them
where only an administrator can read them.

Re-running the installer replaces the line rather than adding a second, and
leaves every other line in that crontab as it was. The account is shared with
a beamline, so that crontab may hold other people's jobs.

### The guard on the API

The moment the API answers, every conductor takes whatever was dispatched to
its beamline and never taken up. After a boot that can be work queued days
earlier, for a sample long since unloaded, in somebody else's beamtime. So the
job starts the database and the JWKS freely and starts the API only when
`nothing-is-queued.sh` finds no execution dispatched and neither claimed nor
ended, and none parked since it was last claimed. A parked execution counts
because a conductor takes it back the moment its handed-off work is reported
stopped, and its next step may move the station. When it finds some, the API
stays down and the journal lists each one: beamline, procedure, when it was
dispatched, its id, and whether it is dispatched or parked.

The guard reads the event log rather than the execution summary, as
`keeper_app`, over the container's local socket. `install.sh` runs it once
after the API is up and refuses if it cannot read the queue, because a guard
that cannot read holds the API after every reboot.

**Releasing a hold** is a decision about stations, so it is a person's:

1. Stop the conductor at each beamline the hold names, on that beamline's
   host: `systemctl --user stop cora-conductor.service`.
2. Start the API here: `systemctl --user start cora-keeper.service`. The guard
   holds only the job; a person starting the unit is not asked.
3. End each execution that should not run or go on, with that beamline's
   token: `POST /executions/<id>/end`. A parked one takes an ending like any
   other live execution, and its handed-off work runs on regardless.
4. Start the conductors again.

Starting the API while the conductors are running hands them the whole queue
at once, which is the thing the hold exists to prevent.

**What the guard does not cover.** It holds the API only on a boot where the
manager missed the units, because that is the only boot this job acts on. On a
boot where the home is mounted in time, the boot starts all three units
itself, the API included, without asking the guard, exactly as it did before
any of this existed. Closing that means taking the API off the default target
so that every boot goes through the job, which changes how a person starts it
as well, and is a separate decision.

### What it asks of the facility

Three things, each checked by `install.sh` before it changes anything, and
each a refusal rather than a warning: a `crontab` command and a running cron
daemon, `flock`, and permission for the account to use cron on this host. On a
host with an `/etc/cron.allow`, that permission is an administrator's to give.

Nothing else. In particular no root, which is the property every installer
here keeps.

### What else was weighed

**Ordering the user manager after the home**, by an administrator. A drop-in
for this account's `user@<uid>.service` on this host would close the race at
its cause, for every unit the account has here. Its shape depends on how the
host mounts homes, which is a read for the administrator: after `autofs.service`
where an automounter serves them, or `RequiresMountsFor=` the home where
`/etc/fstab` does. It needs root once per host, and it does not replace the
job. **Ask for it only after deciding the gap above**: with it in place every
boot finds the home in time and starts the API itself, unguarded.

**Keeping this host's unit files off the shared home.** Outside the home, the
only unit directories a user manager reads that survive a reboot are the
system's, so this needs root on every deploy rather than once. It would also
gain little: the code and the virtualenv the units start are in the home
regardless, and the API would come back unguarded.

### Checking it without a reboot

Rebooting the central host is not a test to run casually, and none of this
needs one. The installer's own output says what it armed and whether the guard
can read the queue. After that, on the host:

```bash
crontab -l | grep cora-keeper-after-boot
ls -l --time-style=+%T "/run/user/$(id -u)/cora-keeper-after-boot.lock"
./nothing-is-queued.sh; echo "exit $?"
```

The first shows the line. The second changes every five minutes, because each
tick that finds a manager opens it: cron's own log belongs to root on a stock
install, so this is how the account itself sees that cron is running the job.
The third is the guard by hand, read only, with the same exit codes the job
reads.

Moving the keeper to another host leaves the old host's line behind. It does
nothing there, because the units are pinned to the new host, and `crontab -e`
on the old host removes it.

## The files

| | |
| --- | --- |
| `install.sh` | preflight, secrets, virtualenv, tokens, certificate, units, migrations, start |
| `issue_tokens.py` | the signing key, the JWKS, one token per caller |
| `issue_tls.py` | the private CA and the server certificate |
| `cora-keeper-postgres.service.in` | the database, a rootless container |
| `cora-keeper-jwks.service.in` | the public key, served for the verifier |
| `cora-keeper.service.in` | the HTTP surface |
| `after-boot.sh` | the cron job that starts what a boot missed, byte-identical in every app that arms one |
| `nothing-is-queued.sh` | the guard that holds the API back while work is queued |
| `queued-executions.sql` | the query that guard runs against the event log |

The templates carry `@NAME@` placeholders and name no host, so the tracked
copy shows the shape and the installed copy shows the deployment.
