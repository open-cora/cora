# Ophyd adapter spike

**This is not production code and nothing in `apps/api` or `apps/reporter`
depends on it.** Read [FINDINGS.md](FINDINGS.md) first; the findings are
the deliverable and the scripts are only how they were obtained.

## Why it exists

The next context is one for equipment: what hardware this system knows
about, and what state it was reported in. The design settled on an
aggregate whose disposition is registered, faulted, restored or
withdrawn, and on an external reference naming the device outside this
system. Three questions gate its first migration, and all three are about
a real library rather than about the model.

1. Does a device have an identity that survives a restart, and if so
   what carries it?
2. Is a fault durable and readable, or visible only to whoever was
   subscribed when it happened?
3. Where does ophyd itself think one device stops?

The sibling spikes are the precedent for how this project answers those:
drive the real thing, print what happened, and let the wire overrule the
documentation. `spikes/bluesky_adapter/` changed the run model twice in
ways reading could not have, and `spikes/tomoscan_adapter/` found that
AROC's three endings were finer than what a second engine emits. Both ran
before the thing they were about was written, and so does this.

The answers are: the PV prefix and nothing else, no, and nowhere the
facility can see. A fourth question turned up on the way, about what a
client reports for a device it cannot reach, and section 4 of the
findings is the sharpest result here.

## What is real and what is not

There is no beamline here and no EPICS installation. `ioc.py` serves the
records with caproto, which speaks Channel Access from Python, and ophyd
connects to it through pyepics the way it connects to a real IOC.

Against that, `observe.py` uses ophyd's own `Device`, `Component`,
`EpicsMotor`, `EpicsSignal` and `EpicsSignalRO`, imported from the
installed package and not overridden. `read`, `read_configuration`,
`describe`, `walk_signals`, `wait_for_connection`, `connected`,
`alarm_severity` and `alarm_status` are all ophyd's. The motor is
caproto's own `motor` record simulator, so `EpicsMotor` connects to a
full motor record rather than to a set of PVs chosen to please it.

The camera's records are hand-written rather than an areaDetector
database, and the temperature alarm is set by the IOC rather than
computed by a record from its HIHI and HHSV fields. That changes who
decided the severity, not what a client can see of it, and what a client
can see is the whole subject. What is left untested is stated at the end
of the findings.

## Which ophyd

`github.com/bluesky/ophyd`, the hardware abstraction layer the Bluesky
collaboration maintains and the one APS beamlines build device profiles
on. Not `ophyd-async`, which is the newer rewrite with a different API;
if this spike is repeated against that, the identity and boundary
findings are the ones most likely to move.

## Why it lives outside `apps/`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane.
Those are all invoked with explicit paths inside `apps/api` and
`apps/reporter`, so a directory at the repo root is invisible to them.
That is deliberate, and the same reasoning as the sibling spikes: code
that has to satisfy the architecture fitness suite is a landing, and the
value of a spike is being able to write it fast and throw it away.

It is also the only place allowed to name the products involved, for the
reason `test_the_domain_names_no_product.py` gives: which control layer a
deployment runs is a deployment's fact, and a rule stated for one reads
as a rule derived from one.

The dependencies are pulled in per invocation rather than added to any
`pyproject.toml`, so there is no dependency, no lockfile churn and no CI
lane touched.

## Running it

```sh
uv run --with caproto --with ophyd --with pyepics \
    python spikes/ophyd_adapter/observe.py
```

It starts the soft IOC itself, runs four scenarios, kills and restarts
the IOC during the last of them, prints everything and writes
`observations.json`. Takes about forty seconds and needs no network
beyond the first install.

**It serves on Channel Access port 5074 rather than the default 5064.**
Two caproto servers cannot both bind a port: whichever starts second
fails, and its client then searches and times out. A sibling spike serves
its own IOC on the default, and moving this one leaves both runnable at
the same time. `ioc.py` sets the server variable and `observe.py` sets
the matching client one.

A line about `broadcast_beacon_loop` failing to reach `127.0.0.1:5065` is
caproto announcing itself where no repeater is listening. Harmless, and
unrelated to anything measured. So is the `Virtual circuit disconnect`
warning during the outage scenario, which is the client noticing the IOC
being killed on purpose.

## The files

```
   ioc.py               a motor, a camera and a proposal's user fields
   observe.py           four scenarios, real ophyd devices, one probe
   observations.json    what a client saw
   FINDINGS.md          the point
```

## When to delete it

When the model questions in section 7 of the findings are answered, which
is the only reason it exists. Keep `observations.json` if an equipment
reporter is ever written: it is what a client actually saw, and it makes
a fixture that needs neither EPICS nor a beamline.
