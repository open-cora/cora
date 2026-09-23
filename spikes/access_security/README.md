# Access security spike

**This is not production code and nothing in `apps/api`, `apps/reporter`
or `apps/conductor` depends on it.** Read [FINDINGS.md](FINDINGS.md)
first; the findings are the deliverable and the scripts are only how they
were obtained.

Whether an IOC can refuse a write from a client that never heard of AROC,
per record, decided at runtime, and what a refusal looks like to the
library `conductor.adapters.epics_control` already uses.

The name is the family marker the other adapter spikes carry, and access
security is the system being asked about even though it is a feature of
EPICS base rather than a package of its own.

## Why it exists

Every mechanism the conducting work has looked at so far is cooperative.
`Ledger` is in-process, so it binds one walk. Queueserver's lock binds
queueserver clients. Sardana's reservation binds Sardana macros. None of
them binds a scientist at an IPython prompt, a SPEC session, or the
TomoScan IOC at 2-BM-S, and `spikes/conductor/` measured what those do to
a running scan: four collisions, four runs reporting
`exit_status: "success"`, one of them recording four of six points at a
single position.

Access security is the only candidate that lives on the other side of the
wire. The IOC decides, so a client that never opted in is still bound.
The requirements document for it was written at ANL/APS in 1992, which
makes it the oldest answer to this question and the one closest to home.

Five questions:

1. Does a rule gated on a PV actually decide a write, and how long does a
   client take to find out? A claim taken at the start of a step is
   useless if the notification arrives after the step does.
2. What does pyepics see when a write is refused? `epics_control` has to
   answer `Refused` here and `Broke` for a motor that would not move, and
   the two are the same call.
3. Is the refusal per record, or does claiming one motor quiet the
   beamline? This is the property queueserver's lock does not have.
4. Can a group tell this process from another one beside it? Two clients
   on one workstation are the same user on the same host.
5. Does `TRAPWRITE` leave a usable record of who collided?

`FINDINGS.md` is the point. All five are answered there.

## What is real and what is not

The IOC is EPICS base's own `softIoc`, reading a database and an access
configuration file, serving Channel Access on a real socket. Nothing is
patched, subclassed or told that a test is happening. Every write goes
out through pyepics, which is the library the conductor's control adapter
uses, and the rival in question 4 is a separate interpreter rather than a
thread, because a thread would share this process's CA context and
therefore its identity.

`ascheck`, base's own syntax checker, validates `access.acf` before the
IOC ever loads it.

Not real: the records. These are `ao` records, not motors. What is under
test is permission rather than motion, and a motor record would add a
readback, a done flag and travel time to a question that has none of
those in it. `spikes/conductor/` is where motors are real.

Also not real: who holds the gate. Both claim records sit in `DEFAULT`,
so anything on the network can set them. A deployment would have to
answer that, and question 4 turns out to decide how.

**caproto cannot serve this spike**, which is worth stating because every
other Channel Access test in this repository uses it. caproto 1.3.0
serves an `ASG` field on every record, because it mirrors the record
definition, and implements nothing behind it: no access file, no groups,
no write-access enforcement anywhere in `caproto/server/`. A spike built
on the existing harness would assign records to groups, write to them
freely and report that all was well.

## Running it

EPICS base is needed and is not a Python package. From conda-forge:

```sh
conda create -n aroc-epics -c conda-forge epics-base
```

Then, from this directory, with base's binaries on `PATH`:

```sh
export EPICS_CA_SERVER_PORT=5084
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1

softIoc -S -m "P=aroc-as:,ME=$USER,OTHER=nobody-here" \
    -a access.acf -d records.db > ioc.log 2>&1 &
```

Then, with the IOC up:

```sh
export PYEPICS_LIBCA=<conda-prefix>/envs/aroc-epics/epics/lib/<arch>/libca.dylib
uv run --no-project --python 3.13 --with pyepics python probe.py
```

Port 5084 is deliberate. `spikes/conductor/` serves on the default 5064
and `spikes/ophyd_adapter/` on 5074, and two sessions sharing this
checkout have collided on a Channel Access port once already.

`ME` and `OTHER` are what make question 4 askable without a second
account: `m1` is claimed by a user nobody here is, and `m2` by the user
running the probe. `findings.json` is what the probe wrote and
`FINDINGS.md` reads it.

## The files

```
   records.db      three writable records and two gates
   access.acf      two gated groups and a default, one holder each
   probe.py        five scenarios, and the rival subprocess
   findings.json   what the IOC refused and what it allowed
   ioc.log         the IOC's own output, which question 5 reads
   FINDINGS.md     the point
```

## When to delete it

When the instrument-ownership question is settled, which is the only
reason it exists. Keep `access.acf` if a claim service is ever written:
the gated-rule shape in it is the part that took the longest to get right
and the part a deployment would copy.
