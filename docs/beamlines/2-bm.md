# 2-BM

*Bending-magnet micro-CT at the Advanced Photon Source, and the first
beamline this system was pointed at. A conductor and a reporter run here
against a simulator, and the whole chain from dispatch to a described file
has been walked.*

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

## What runs here

A conductor, a reporter and both simulators, all on arcturus. 2-BM is the
only beamline where the simulators share a host with the conductor, and
that is a measured compromise rather than the pattern.

| | where | what it is pointed at |
| --- | --- | --- |
| conductor | arcturus | `corasim2bmb:` to write, `corasim2bmb:TomoScan:` to run |
| reporter | arcturus | the records at `corasim2bmb:TomoScan:` |
| simulated motors | arcturus | `corasim2bmb:` on port 5065 |
| simulated TomoScan | arcturus | `corasim2bmb:TomoScan:` on port 5066 |

**Why the simulators are not on an IOC host.** This beamline's motors are
served by a crate rather than a workstation, so the only host available is
the one serving the scan server, and that host has five network interfaces,
two of them link local. A Channel Access server there advertises on all of
them, and a client that can route to only one of the five sees a name
answered from an address it cannot reach. That is the condition recorded
here for a long time as two servers fighting over one name; it is one
multi-homed host, and it is a poor place to add a server of ours at a
beamline in operations.

**What that costs is worth stating plainly.** A conductor reaching a
simulator on its own host proves the software and not the beamline network.
The network half is proven at the other three, including the one where
broadcast does not work at all, so what is missing here is a fourth
instance of a result rather than the result.

**No package index reaches this host**, which is the other thing that makes
2-BM different. Its virtualenvs are built on the central host, which shares
the same home over NFS and runs an older C library, so wheels resolved there
load here and not the other way round. The build is a deliberate step on
another machine rather than a flag on the installer.

## What this does not establish

Nothing here has written to a record this system does not serve itself. The
conductor is confined to the simulator's prefix and refuses anything else,
which has been exercised against a refusal rather than assumed. So whether a
write to one of this beamline's real motors would be permitted is untested,
and that is a question for IOC access security and for beamline staff.
