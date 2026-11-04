# The transfer engines this repository ships

`run.profile` names something importable that hands back an engine seam.
`conductor.adapters.globus_transfer` declares what it needs of a transfer
service and imports nothing, so a deployment that moves files has to point
that setting at something which does.

One of them, and it is not the only possible one: a facility that moves
data another way writes its own and points `PROFILE_PATH` and
`run.profile` at that instead.

| profile | reaches | what it is for |
| --- | --- | --- |
| `globus:engine` | Globus Transfer | moving a beamline's files to a computing facility |

## Why it is here and not in the package

Three of the four beamlines this system serves will never move a byte
through Globus, and two libraries and a token store is a great deal to
install at all of them so that one can. The adapter stays dependency
free and this carries the dependency, which is the same split the
thinker draws between its seam and `infra/thinking`.

## What the unit has to set

| variable | holds |
| --- | --- |
| `CORA_TRANSFER_SOURCE` | the collection a beamline publishes from |
| `CORA_TRANSFER_DESTINATION` | the collection data is staged to |
| `CORA_TRANSFER_PREFIX` | the directory under it that files land in |
| `CORA_TRANSFER_ROUTINE` | the routine name, when it is not `transfer` |
| `CORA_TRANSFER_SETTLE_SECONDS` | how long a walk waits before handing off |

The first three have no defaults and a missing one stops the engine being
built, which happens at startup. A deployment that got one wrong finds out
before a procedure reaches a transfer rather than during one.

None of them is a credential. `alcf_tokens` reads the facility's token
store, and the account the conductor runs as is the account that store
belongs to, which is the part of this that is arranged outside any file
here.

## Placement follows the credential

This engine needs network egress to Globus and a token store, and nothing
else. It does not need Channel Access, so nothing pins it to a beamline,
and a deployment is free to run it wherever those two things are.

Where they are is a measured fact rather than a preference. The account
that has completed the consent flow is the one whose home holds the
tokens, and a host that reaches a beamline's detector is not necessarily
a host that reaches the internet.
