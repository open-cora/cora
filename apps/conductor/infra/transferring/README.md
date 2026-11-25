# The transfer engines this repository ships

`run.profile` names something importable that hands back an engine seam.
`conductor.adapters.globus_transfer` declares what it needs of a transfer
service and imports nothing, so a deployment that moves files has to point
that setting at something which does.

Three of them, and they are not the only possible ones: a facility that
moves data another way writes its own and points `PROFILE_PATH` and
`run.profile` at that instead.

| profile | reaches | what it is for |
| --- | --- | --- |
| `transfers:mover` | Globus Transfer | moving data between named places, along the routes a deployment installed |
| `transfers:engine` | Globus Transfer | moving a beamline's files to a computing facility |
| `transfers:homeward` | Globus Transfer | bringing a result back to the beamline |

The mover is the one to name. The other two stay so that a host whose run
tables already name them needs no edit, and they go when none does.

## Places, routes and a path

A **place** is a name the facility gives somewhere data can be: a
beamline's published data, a computing facility's staging area. The move
operation's schema in the facility register lists the names, so a
procedure can only write one that exists. What a name leads to, a
collection and a root folder on it, is set here and nowhere a procedure
can reach.

A **route** is one move this conductor may make, from one place to
another. Nothing else moves, whatever a step asks for.

A step is `move` with three parameters:

```toml
parameters = { path = "2026-2/sample_0004.h5", from = "19-bm", to = "alcf" }
```

`path` is where the data sits inside the place it leaves, relative to that
place's root, and it lands at the same relative path inside the place it
reaches. So one path names the data at every stop of a chain, and a chain
of any length is the same operation at each hop with only `from` and `to`
changing. A path ending in a slash is a folder and everything under it. A
path that starts with a slash, or has an empty, "." or ".." segment, is
refused before anything is submitted, because a place's root is the bound
on what a step can reach.

```toml
[[run]]
profile = "transfers:mover"
routines = ["move"]
```

## Why the trip home was a second engine

An engine is given its source collection and its destination collection
when it is built, and a step may name neither, which is the whole of why
a procedure cannot move a beamline's data somewhere it was not sent. The
price of that is directional: one engine moves files one way.

So a round trip is two engines in one conductor, named in two run
tables, answering to two routines. They differ in six strings and share
everything else, which is why they are one module rather than two.

```toml
[[run]]
profile = "transfers:engine"
routines = ["transfer"]

[[run]]
profile = "transfers:homeward"
routines = ["retrieve"]
```

A deployment that only sends data away names the first and nothing else
changes.

The mover keeps the rule and drops the price. Its routes are the pairs,
installed by the deployment, and one engine holds every one of them, so a
round trip is two steps of one operation rather than two operations.

## Why it is here and not in the package

Three of the four beamlines this system serves will never move a byte
through Globus, and two libraries and a token store is a great deal to
install at all of them so that one can. The adapter stays dependency
free and this carries the dependency, which is the same split the
thinker draws between its seam and `infra/thinking`.

## What the unit has to set

For the mover:

| variable | holds |
| --- | --- |
| `CORA_MOVE_PLACES` | each place this conductor knows, as name=collection:root, separated by spaces |
| `CORA_MOVE_ROUTES` | each move it may make, as from>to, separated by spaces |
| `CORA_MOVE_ROUTINE` | the routine name, when it is not `move` |
| `CORA_MOVE_SETTLE_SECONDS` | how long a walk waits before handing off |

```sh
CORA_MOVE_PLACES=19-bm=<collection id>:/ alcf=<collection id>:/<staging folder>
CORA_MOVE_ROUTES=19-bm>alcf alcf>19-bm
```

The first two have no defaults. A place name is lowercase letters, digits
and hyphens, and a root is an absolute path on its collection. A missing
setting, a route naming a place that is not listed, or a route that
leaves and arrives at one place stops the engine being built, which
happens at startup, so a deployment that wrote one wrong finds out before
a procedure reaches a move rather than during one.

For the older engines, the trip out:

| variable | holds |
| --- | --- |
| `CORA_TRANSFER_SOURCE` | the collection a beamline publishes from |
| `CORA_TRANSFER_DESTINATION` | the collection data is staged to |
| `CORA_TRANSFER_PREFIX` | the directory under it that files land in |
| `CORA_TRANSFER_ROUTINE` | the routine name, when it is not `transfer` |
| `CORA_TRANSFER_SETTLE_SECONDS` | how long a walk waits before handing off |

And the trip home, the same five with the collections the other way round:

| variable | holds |
| --- | --- |
| `CORA_RETRIEVE_SOURCE` | the collection results are computed onto |
| `CORA_RETRIEVE_DESTINATION` | the collection the beamline reads |
| `CORA_RETRIEVE_PREFIX` | the directory under it that results land in |
| `CORA_RETRIEVE_ROUTINE` | the routine name, when it is not `retrieve` |
| `CORA_RETRIEVE_SETTLE_SECONDS` | how long a walk waits before handing off |

The first three of each family have no defaults and a missing one stops
that engine being built, which happens at startup.

The two families are separate so that they cannot be confused, and that
is load bearing rather than tidy. One process holds one environment, so
a homeward engine reading the outbound variables would be built pointing
the same way as the outbound one: it would send the result to the
computing facility again, succeed, and leave the record saying a result
came home.

None of them is a credential. `alcf_tokens` reads the facility's token
store, and the account the conductor runs as is the account that store
belongs to, which is the part of this that is arranged outside any file
here.

## A fault that waiting will not cure

Transfer retries everything until a task's deadline, which is a day
after it was asked for, and it retries a missing file exactly as
patiently as a busy endpoint. Measured: a transfer whose source does
not exist sits in `ACTIVE` for the full day, accumulating faults, with
the reason only in `nice_status`.

An engine told only the status cannot tell that from a large file still
moving. Both run past the bound, both are handed off, and the record
never says which happened. So this profile reads `nice_status` too, and
reports a fault from the `HOPELESS` set as a failure with the reason
attached rather than waiting it out. Measured again afterwards: refused
in 34 seconds saying `FILE_NOT_FOUND after 1 attempts`, where before it
was handed off at 154 seconds saying nothing.

What is not in that set matters as much as what is. A failed
connection, a busy endpoint and a paused one are all states a transfer
recovers from, and calling them failures would turn a slow afternoon
into a procedure that refused.

**A task refused this way is still running at the service.** Nothing
here cancels it, for the reason the adapter gives: a walk's verdict is
a fact about this process rather than about the work. It stops at its
own deadline. A deployment that wants them reaped sooner does that from
outside, and should, because a task left retrying could still succeed
after the record said it failed.

## Placement follows the credential

This engine needs network egress to Globus and a token store, and nothing
else. It does not need Channel Access, so nothing pins it to a beamline,
and a deployment is free to run it wherever those two things are.

Where they are is a measured fact rather than a preference. The account
that has completed the consent flow is the one whose home holds the
tokens, and a host that reaches a beamline's detector is not necessarily
a host that reaches the internet.
