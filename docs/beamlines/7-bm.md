# 7-BM

*High-speed imaging and micro-tomography at the Advanced Photon Source, and
the most straightforward of the four surveys. A conductor and a reporter run
here against a simulator, and the whole chain from dispatch to a described
file has been walked.*

A beamline descriptor is what a running keeper has to be told about the
beamline it serves. The rule that keeps it short is in
[`beamlines/README.md`](https://github.com/open-cora/cora/blob/main/beamlines/README.md).

## The device register

[`beamlines/7-bm/devices.toml`](https://github.com/open-cora/cora/blob/main/beamlines/7-bm/devices.toml)
holds three devices, all confirmed: a sample rotation stage and two hexapod
axes carrying the sample.

All three came from asking the acquisition software which records it drives,
which is record to record with nothing translated between one system's model
and another's, and each was then read back to confirm it answers. That
read-back is not ceremony. The same question at 19-BM returns two strings
that name nothing, and reading them back is what tells the two cases apart.

The register is the same shape as 2-BM's, and so is the hardware: a rotation
stage and a hexapod, with the facility's own description fields calling the
sample axes Hexapod X and Hexapod Y at both. The names here are authored, as
they are everywhere in this directory, because a description field says what
carries an axis rather than what the axis is for.

**Two of these three rows are expected to move to another beamline.** 19-BM's
own manual describes a placeholder prefix for hardware not yet installed
there and says it covers "the hexapod coming from 7-BM". The hexapod is what
carries `7bmbHXP:m2` and `7bmbHXP:m3`, so if it moves, this register keeps a
rotation stage and loses its two sample axes, and 19-BM gains them under
addresses nobody has assigned yet.

Nothing here would notice. A register row is a record name, a device is
registered in the keeper by that name, and neither side has anything that
asks the beamline whether the hardware is still present. That is the same
silence [`beamlines/README.md`](https://github.com/open-cora/cora/blob/main/beamlines/README.md)
records for a mismatched beamline name, met from the hardware side instead,
and the answer is the same one: re-sweep rather than trust the file.

The detector is named as a prefix and is therefore not a row, which is the
exclusion every register here makes for the same reason.

## What runs here

A conductor and a reporter, both as `systemd --user` services on the routable
host, and two simulators on a private one. The conductor is confined to the simulator's own
prefix and could not write to this beamline's hardware if a procedure named
it.

| | where | what it is pointed at |
| --- | --- | --- |
| conductor | the routable host | `corasim7bm:` to write, `corasim7bm:TomoScan:` to run |
| reporter | the routable host | the records at `corasim7bm:TomoScan:` |
| simulated motors | a private host | `corasim7bm:` |
| simulated TomoScan | a private host | `corasim7bm:TomoScan:` |

The reporter reads TomoScan's records rather than a document stream.
TomoScan's stream has no documents in it, which
`spikes/tomoscan_adapter/FINDINGS.md` measured at 2-BM, and a source that
reads records is what removed the barrier.

A dispatched scan walks to `Done`, the simulator writes the file it
announces, and the reporter files the address and a description of what is
inside it. The description is read back out of the file by `h5py`, so it
tracks what was asked for rather than repeating it: a scan of sixteen angles
gives a `/exchange/theta` extent of sixteen.

## What this does not establish

**Nothing here has touched the beamline's own hardware.** Every record
written is one this system serves itself, which is the standing rule for a
deployment at a beamline in operations. So the register's three devices are
read and never driven, and whether a write to one would be permitted is
untested: that is a question for IOC access security and for beamline staff,
and a write that succeeds moves hardware.

**The file is a simulated one.** Its arrays are declared at full shape and
never written, so it is a few tens of kilobytes where a real frame at this
facility is measured in hundreds of megabytes. The describing leg has been
proven against the shape of a real file and not against its size.
