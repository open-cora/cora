# 2-BM

*Bending-magnet micro-CT at the Advanced Photon Source, and the first
beamline this system is being pointed at. Nothing is deployed there yet;
what exists is the descriptor and the one script that reads it.*

## What a descriptor is here

A beamline descriptor is what a running AROC has to be told about the
beamline it serves, written down where it can be read and reviewed rather
than passed on the command line or remembered.

It is a short file, and the shortness is a rule rather than an accident:
**a descriptor may only carry a field that some AROC command or client
configuration accepts today.** Equipment holds an address, a label and a
derived status, and [says at length](../bounded-contexts/equipment.md) why
it holds no family, no configuration, no readings and no tree. A descriptor
field with no consumer would be a claim about 2-BM that nothing here can
act on and nothing here can contradict.

The full rule, and what it costs, is in
[`beamlines/README.md`](https://github.com/xmap/aroc/blob/main/beamlines/README.md).

## The device register

[`beamlines/2-bm/devices.toml`](https://github.com/xmap/aroc/blob/main/beamlines/2-bm/devices.toml)
is the list of hardware AROC will hold a record of. Three keys per row:

```toml
scheme = "epics-record"

[[device]]
ref = "2bmb:m1"
name = "Sample rotation"
confirmed = false
```

`ref` is where the control system publishes the device. `name` is this
system's own label, authored here and never copied from the facility's
description field. `confirmed` says whether the row was checked against the
beamline or read off documentation, and it is the one field describing the
record rather than the hardware.

**The register is empty today.** Rows come from a `caget` sweep against
2-BM's own IOCs or from staff, and nothing in this repository is
transcribed from elsewhere, so it stays empty until somebody has run one.
The count is pinned at zero in `beamlines/tests/`, for the reason
`test_fitness_scope.py` pins its own counts: the check that every reference
is well-formed ranges over this file, and over an empty file it passes
while verifying nothing.

## The one rule on a reference

A device's external reference is **one record, normalized**: trimmed, cut
at the first `.`, with any trailing `:` removed. So `2bmb:m1.RBV` and
`2bmb:m1.VAL` are both `2bmb:m1`, and a reference never ends in `:`.

Two spikes reached this independently.
a spike
built one motor twice from two startup profiles and watched it answer to
two names at once, with nothing recording that they were one device.
a spike
asked what two writers can be said to share, and got the same answer from
the other side. The record name is what the IOC serves and the only string
two clients who have never met must agree on; the facility's own `DESC`
field is served empty and writable by anyone.

References are stored already normalized, and the loader refuses one that
is not rather than quietly converting it. Equipment enforces no uniqueness
across devices, so two spellings of one motor are two records that nothing
notices, and a caller resolving a device is about to write to whatever
comes back. The file is the only place that can be caught.

The scheme is `epics-record`. The spike wrote `epics-prefix`, which
predates the record and namespace split in `conductor.claims`; under the
rule above the value is never a namespace, and a scheme string goes onto
every `DeviceRegistered` event permanently.

## Seeding

`beamlines/seed_devices.py` reads a register, resolves each reference
against `GET /devices`, and posts the ones that are not there. Run it with
`--dry-run` first.

It is not idempotent and does not claim to be. The resolve is a check and
not a lock, because Equipment has no uniqueness constraint behind it; the
`Idempotency-Key` it derives per device narrows the window without closing
it, since the key expires after `IDEMPOTENCY_TTL_HOURS` and is scoped to
the calling principal. An address that already carries two records is
reported and not resolved: which one an adapter should write to is not a
question this script can answer.

## What is not modeled here

**No composition.** The sibling project pairs a device inventory with
assemblies and fixtures. The equivalent in this tree is a
`conductor.procedure.Procedure` over claims, and it is client-side: a claim
may be coarser than a device and never finer, so the join runs one way,
`scope.covers(Scope.record(ref))`. No procedure descriptor exists yet,
because the conductor has never started a scan at a real beamline and a
descriptor written before that would be the guessing the spikes exist to
replace.

**No reporter settings.** `apps/reporter` reads the documents a Bluesky
RunEngine publishes. 2-BM-S runs TomoScan, whose stream
has no documents in it at all,
which also has no run identity until a scan ends and nothing to key a plan
map on. Pointing the reporter at 2-BM is therefore not a configuration
question yet. See the plan for what would have to change.

**No safety or access configuration.** An IOC can refuse a write from a
client that never opted in, measured in
a spike,
and an access file belongs to the beamline. It is not in the descriptor
because nothing in this tree reads one.
