# The compute engines this repository ships

`run.profile` names something importable that hands back an engine seam.
`conductor.adapters.globus_compute` declares what it needs of a compute
service and imports nothing, so a deployment that reconstructs data has
to point that setting at something which does.

One of them, and it is not the only possible one: a facility that
reconstructs another way writes its own and points `PROFILE_PATH` and
`run.profile` at that instead.

| profile | reaches | what it is for |
| --- | --- | --- |
| `reconstructions:engine` | Globus Compute | reconstructing a dataset at a computing facility |

## Why it is here and not in the package

Most beamlines this system serves will never submit a job, and an SDK
and a credential is a great deal to install at all of them so that one
can. The adapter stays dependency free and this carries the dependency,
which is the same split `../transferring/README.md` describes and the
same one the thinker draws between its seam and `infra/thinking`.

## What the unit has to set

| variable | holds |
| --- | --- |
| `CORA_COMPUTE_ENDPOINT` | the Globus Compute endpoint to submit to |
| `CORA_COMPUTE_PROJECT` | the project the allocation is charged to |
| `CORA_COMPUTE_QUEUE` | the scheduler queue, when it is not `demand` |
| `CORA_COMPUTE_IMAGE` | the absolute path to the container, on the compute node |
| `CORA_COMPUTE_SETUP_ENV` | a script to source first, when there is one |
| `CORA_COMPUTE_BIND_SOURCE` | the host directory bound into the container |
| `CORA_COMPUTE_BIND_TARGET` | where that directory appears inside it |
| `CORA_COMPUTE_RESULTS` | where results go, as a container path |
| `CORA_COMPUTE_DEFAULTS` | a file of reconstruction settings a step may omit |
| `CORA_COMPUTE_NODES` | nodes per block |
| `CORA_COMPUTE_WORKERS_PER_NODE` | workers per node |
| `CORA_COMPUTE_ACCELERATORS` | accelerators per node |
| `CORA_COMPUTE_WALLTIME` | the job's walltime, when it is not the endpoint's default |
| `CORA_COMPUTE_ROUTINE` | the routine name, when it is not `reconstruct` |
| `CORA_COMPUTE_SETTLE_SECONDS` | how long a walk waits before handing off |

`ENDPOINT`, `PROJECT`, `IMAGE`, `BIND_SOURCE`, `BIND_TARGET` and
`RESULTS` have no defaults and a missing one stops the engine being
built, which happens at startup. A deployment that got one wrong finds
out before a procedure reaches a reconstruction rather than during one.

None of them is a credential. Globus Compute reads the same token store
the transfer engine does, and the account the conductor runs as is the
account that store belongs to.

**The four sizing variables decide what the project is charged**, and
they are deliberately here rather than in a step. A procedure able to
name its own node count could spend an allocation while reading like any
other step.

## The defaults file

Tomocupy takes dozens of settings and a unit carrying dozens of
environment variables is a unit nobody reads. So they go in a file:

```toml
[defaults]
reconstruction-type = "full"
reconstruction-algorithm = "fourierrec"
remove-stripe-method = "vo-all"
fbp-filter = "parzen"
retrieve-phase-method = "paganin"
rotation-axis = 1628.5
energy = 92.0
pixel-size = 3.44
propagation-distance = 420.0
```

A step that names one of these overrides it. That is what keeps the
record honest: `beamlines/operations.toml` declares the handful carrying
a unit or a bound, a procedure sets the ones that are decisions about
its dataset, and the rest sit here because they are the same for every
run at this beamline.

Three settings are **not** written here and are refused if they are.
`file-name`, `out-path-name` and `logs-home` are derived from the step's
`source_path` and from `CORA_COMPUTE_RESULTS`, because they are what the
reconstruction is about rather than how it is done.

## Container paths and host paths are not the same path

The reconstruction runs inside a container with `BIND_SOURCE` bound to
`BIND_TARGET`, so everything tomocupy is handed is a container path
while the directories that must exist first are host paths. The profile
converts in both directions. Setting `RESULTS` to a host path is the
mistake to watch for: it produces a job that starts, writes nowhere the
container can see, and exits non-zero.

## What a handoff means here

The usual outcome. A reconstruction runs for hours and a walk holds a
claim for minutes, so the step normally ends with a task id rather than
with a result. That is a record of where the work went, not a failure,
and resolving it later is something else's job.

## What is not tested here

The submission path. Everything in `conductor.adapters.globus_compute`
is covered against a double, because the adapter imports nothing and
needs no network. This file does need one, plus a credential and an
allocation, so what it does is checked by running it rather than by the
suite. Keep the logic here thin for that reason: anything worth a test
belongs on the other side of the seam.
