# 7-BM

*High-speed imaging and micro-tomography at the Advanced Photon Source, and
the most straightforward of the four surveys. Nothing is deployed there;
what exists is the descriptor.*

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

The detector is named as a prefix and is therefore not a row, which is the
exclusion every register here makes for the same reason.

## What is not configured yet

**No conductor configuration.** A conductor is told which beamline it drives
and where to reach the keeper, and there is no keeper host yet.

**No reporter settings.** Not because one could not run here. TomoScan's
stream has no documents in it, which `spikes/tomoscan_adapter/FINDINGS.md`
measured at 2-BM, but a reporter can read TomoScan's records directly and so
needs none. Nothing is installed at this beamline yet, and
[Where each part runs](index.md) sets out the configuration limit that has to
move before one can file anything.
