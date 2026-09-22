# Conductor spike

Whether a conductor can hold a control seam and an acquisition seam
behind one procedure without the two fighting over a device, and what it
leaves behind when it dies.

## Why it exists

The conducting direction puts a `Procedure` in Execution and an
orchestrating app beside `apps/reporter`, driving hardware through
several seams: EPICS or Tango underneath, Bluesky or TomoScan above, a
store and a transfer service beside them. The seams are named by the
system they abstract, which is the natural way to name them and may be
the wrong way to cut them.

Nothing in that sketch stops one step from moving a device while another
step scans it. This asks what happens when one does, because the answer
decides what a procedure step has to declare before it runs, and that is
a decision to make before an aggregate exists rather than after.

Three questions:

1. Does the control and acquisition split survive two writers on one
   device, and does anything notice when it does not?
2. What identity does a conducted run have at the moment it is
   submitted, given that `external_ref` is required at a run's genesis?
3. What does a conductor come back to, if it comes back?

`FINDINGS.md` is the point. All three are answered there.

## What is real and what is not

There is no beamline here and no EPICS installation. `ioc.py` serves
caproto's own `FakeMotorIOC`, which speaks Channel Access from Python,
and ophyd connects to it the way it connects to a real IOC.

Against that, the scans are Bluesky's own `scan` driven by a real
`RunEngine` over a real `EpicsMotor`, and the rival writes go out of a
separate process through pyepics. Neither the engine nor ophyd is
patched, subclassed or told that any of this is happening, so what the
scenarios record is what those packages do.

The simulator is imported rather than reimplemented. A motor written here
would be a guess about what a motor does, and a lenient guess would
answer question 1 by construction.

Not real: the detector. `SynGauss` computes a value from the motor's
position rather than reading a camera, which is the property that makes a
corrupted scan legible in the data. A real detector would only make it
harder to see.

## Why it lives outside `apps/`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane.
Those are invoked with explicit paths inside `apps/api` and
`apps/reporter`, so a directory at the repository root is invisible to
them. Same reasoning as the sibling spikes: code that has to satisfy the
architecture fitness suite is a landing, and the value of a spike is
being able to write it fast and throw it away.

Dependencies are pulled in per invocation rather than added to any
`pyproject.toml`, so there is no dependency, no lockfile churn and no CI
lane touched.

## Running it

```sh
# From the repository root.

# 1. Four rival writes during a real scan, plus the identity question.
uv run --with caproto --with ophyd --with bluesky --with pyepics \
    python spikes/conductor/collide.py

# 2. Kill a driving process mid-move and watch what is left.
uv run --with caproto --with ophyd --with bluesky --with pyepics \
    python spikes/conductor/orphan.py
```

About a minute together, and no network beyond the first install. Each
starts its own soft IOC, prints what it saw and overwrites its capture.

## The files

```
   ioc.py            three motor records over Channel Access
   collide.py        five scenarios, two writers, one device
   orphan.py         SIGKILL mid-move, and the watch afterwards
   collisions.json   what the scans recorded, all six
   orphan.json       the motor, every half second after the kill
   FINDINGS.md       the point
```

## When to delete it

When the device-claim question in `FINDINGS.md` is answered, which is the
only reason it exists. Keep `collisions.json` if a conductor is ever
written: it is what two writers on one device actually produce, and it
makes a fixture that needs neither EPICS nor a beamline.
