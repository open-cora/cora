# 2-BM

*Bending-magnet micro-tomography at the Advanced Photon Source, and the first
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
because every scan the conductor has started drove a simulator rather than
this beamline's own engine, and a descriptor written before that would be the
guessing the spikes exist to replace.

**No reporter settings.** A reporter runs at 2-BM and the descriptor says
nothing about it, which is the point rather than an omission: what it watches
is a records prefix on the host it runs on, and that is a fact about the
deployment rather than about the beamline.

The blocker this used to record is gone rather than waiting. `apps/reporter`
read the documents a Bluesky RunEngine publishes, and 2-BM-S runs TomoScan,
whose stream has no documents in it at all, which
`spikes/tomoscan_adapter/FINDINGS.md` measured. What removed it was a second
delivery reading the engine's own records instead of a document stream. A
reporter also once had to be told how an engine's routine names mapped onto
this system's own ids, and that setting is gone too: the keeper composes the
work, so the ids travel in the engine's own metadata and nothing is resolved
at this end.

**No safety or access configuration.** An IOC can refuse a write from a
client that never opted in, and an access file belongs to the beamline.
The first of those is carried over from a spike that is not in this tree,
so it is known of Channel Access rather than measured here. Neither is in
the descriptor, because nothing in this tree reads one.

## What runs here

A conductor, a reporter and both simulators, all on one private host. 2-BM
is the
only beamline where the simulators share a host with the conductor, and
that is a measured compromise rather than the pattern.

| | where | what it is pointed at |
| --- | --- | --- |
| conductor | the conductor host | `corasim2bmb:` to write, `corasim2bmb:TomoScan:` to run |
| reporter | the conductor host | the records at `corasim2bmb:TomoScan:` |
| simulated motors | the conductor host | `corasim2bmb:` on port 5065 |
| simulated TomoScan | the conductor host | `corasim2bmb:TomoScan:` on port 5066 |

**The conductor host is itself an IOC host here**, which is not true at any other
beamline and is the thing that makes this placement reasonable rather than
merely convenient. Asked which host answers for each registered device:

```
   2bmb:m102     rotation     a crate, not ours to install on
   2bmHXP:m1     sample X     the conductor host
   2bmHXP:m3     sample Y     the conductor host
```

Two of the three devices in this beamline's register are served from the
same machine the conductor runs on. So a simulator there sits beside a real
IOC rather than on a bare client.

**The host that serves the scan server is a poor third option.** It runs
the TomoScan server and the optics and energy IOCs, and it has five network
interfaces, two of them link local. A Channel Access server there advertises
on all of them and a client that can route to one sees a name answered from
an address it cannot reach. Asked from that host itself, its own
`2bmb:TomoScan:ServerRunning` and the camera's model record both fail to
resolve, while the two motors elsewhere resolve immediately. That is the
condition recorded here for a long time as two servers fighting over one
name. It is one multi-homed host, and it is a poor place to add a server of
ours at a beamline in operations.

**One of the five is not a beamline interface at all.** The facility's own
computing notes put that host on the separate fabric its tomography compute
and storage nodes use, which is why one of the addresses it advertises
answers for nothing a beamline client can route to. The fabric itself is in
the address book rather than on this page. That accounts for one interface
and changes nothing about the conclusion: a server of ours there would still
advertise on all five.

**What the placement costs is still worth stating plainly.** A conductor
reaching a simulator on its own host crosses no network, so what is proven
here is the software rather than the beamline's wiring. The network half is
proven at the other three, including the one where broadcast does not work
at all, so what is missing is a fourth instance of a result rather than the
result.

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
