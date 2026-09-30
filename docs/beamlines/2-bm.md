# 2-BM

*Bending-magnet micro-CT at the Advanced Photon Source, and the first
beamline this system is being pointed at. Nothing is deployed there yet;
what exists is the descriptor and the one script that reads it.*

A beamline descriptor is what a running keeper has to be told about the
beamline it serves, written down where it can be read and reviewed rather
than passed on the command line or remembered. It is a short file, and the
shortness is a rule rather than an accident: **a descriptor may only carry a
field that some keeper command or client configuration accepts today.** The
full rule, and what it costs, is in
[`beamlines/README.md`](https://github.com/open-cora/cora/blob/main/beamlines/README.md).

## The device register

[`beamlines/2-bm/devices.toml`](https://github.com/open-cora/cora/blob/main/beamlines/2-bm/devices.toml)
is the list of hardware the keeper will hold a record of. Three keys per row:

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

**The register holds three devices, and all three are confirmed.** They
came from a `caget` sweep against 2-BM's own IOCs, read out of the
acquisition software's own configuration rather than assembled by hand: a
sample rotation stage and two hexapod axes carrying the sample. Reading the
roles from the software that drives them is what makes them confirmed, and
it is better evidence than a motor number, which says where a thing is
plugged in and not what it does.

The count is pinned in `beamlines/tests/`, for the reason
`test_fitness_scope.py` pins its own counts: the check that every reference
is well-formed ranges over this file, and over an empty file it would pass
while verifying nothing. It sat at zero until the sweep, which is what the
pin was waiting for.

**Two things the sweep found are deliberately not rows.** The detector is
named as a prefix, and a prefix is a namespace rather than a record: asking
for that string alone finds nothing while the records beneath it answer, so
the rule below has no honest way to write it. And the shutter and permit
signals the software reads belong to a facility safety system rather than
to this beamline, which reads them and does not own them.

## How a device reference is written

A device's external reference is **one record, normalized**: trimmed, cut
at the first `.`, with any trailing `:` removed. So `2bmb:m1.RBV` and
`2bmb:m1.VAL` are both `2bmb:m1`, and a reference never ends in `:`.

Two spikes reached this independently. `spikes/ophyd_adapter/FINDINGS.md`
built one motor twice from two startup profiles and watched it answer to
two names at once, with nothing recording that they were one device.
`spikes/conductor/FINDINGS.md` asked what two writers can be said to share,
and got the same answer from the other side. The record name is what the
IOC serves and the only string two clients who have never met must agree
on; the facility's own `DESC` field is served empty and writable by anyone.

References are stored already normalized, and the loader refuses one that
is not rather than quietly converting it. Equipment enforces no uniqueness
across devices, so two spellings of one motor are two records that nothing
notices, and a caller resolving a device is about to write to whatever
comes back. The file is the only place that can be caught.

The scheme is `epics-record`. `spikes/ophyd_adapter/FINDINGS.md` wrote
`epics-prefix`, which predates the record and namespace split in
`conductor.claims`; under the rule above the value is never a namespace,
and a scheme string goes onto every `DeviceRegistered` event permanently.

## Seeding the register

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

Equipment holds an address, a label and a derived status, and the keeper's
Equipment page says at length why it holds no family, no configuration, no
readings and no tree. A descriptor field with no consumer would be a claim
about 2-BM that nothing here can act on and nothing here can contradict.
Three absences are worth naming.

**No composition.** The tree this chassis was copied from pairs a device
inventory with assemblies and fixtures. The equivalent here is a
`conductor.procedure.Procedure` over claims, and it is client-side: a claim
may be coarser than a device and never finer, so the join runs one way,
`scope.covers(Scope.record(ref))`. No procedure descriptor exists yet,
because the conductor has never started a scan at a real beamline and a
descriptor written before that would be the guessing the spikes exist to
replace.

**No reporter settings.** `apps/reporter` reads the documents a Bluesky
RunEngine publishes. 2-BM-S runs TomoScan, whose stream has no documents in
it at all, which `spikes/tomoscan_adapter/FINDINGS.md` measured.

That is now the whole of the blocker, and it used to be half. A reporter once
had to be told how an engine's routine names mapped onto this system's own
ids, and that setting is gone: the keeper composes the work, so the ids
travel in the engine's own metadata and nothing is resolved at this end. So
pointing a reporter at 2-BM is not a configuration question and never
becomes one. It is waiting on something to subscribe to, which
[Where each part runs](index.md) sets out.

**No safety or access configuration.** An IOC can refuse a write from a
client that never opted in, and an access file belongs to the beamline.
The first of those is carried over from a spike that is not in this tree,
so it is known of Channel Access rather than measured here. Neither is in
the descriptor, because nothing in this tree reads one.
