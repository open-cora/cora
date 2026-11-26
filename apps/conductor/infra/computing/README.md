# The compute engine this repository ships

`run.profile` names something importable that hands back an engine seam.
`conductor.adapters.globus_process` declares what it needs of a compute
service and imports nothing, so a deployment that processes data has to
point that setting at something which does.

One builder, and not the only possible one: a facility that processes
data another way writes its own and points `PROFILE_PATH` and
`run.profile` at that instead.

| profile | reaches | what it is for |
| --- | --- | --- |
| `reconstructions:processor` | Globus Compute | processing an input into an output inside a named place, by a named configuration |

It runs tomocupy, so a configuration here is a set of tomocupy settings.
Another program is another profile against the same seam.

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
| `CORA_COMPUTE_PLACES` | the places a process step may name, each `name=folder` on the compute host |
| `CORA_COMPUTE_CONFIGS` | a file of named configurations, for a step that arrives without a setup; optional |
| `CORA_COMPUTE_PROCESS_ROUTINE` | the routine name, when it is not `process` |
| `CORA_COMPUTE_NODES` | nodes per block |
| `CORA_COMPUTE_WORKERS_PER_NODE` | workers per node |
| `CORA_COMPUTE_ACCELERATORS` | accelerators per node |
| `CORA_COMPUTE_WALLTIME` | the job's walltime, when it is not the endpoint's default |
| `CORA_COMPUTE_SETTLE_SECONDS` | how long a walk waits before handing off |

`ENDPOINT`, `PROJECT`, `IMAGE`, `BIND_SOURCE`, `BIND_TARGET` and `PLACES`
have no defaults. A missing one stops the engine being built, which
happens at startup. A deployment that got one wrong finds
out before a procedure reaches a process step rather than during one.

None of them is a credential. Globus Compute reads the same token store
the transfer engine does, and the account the conductor runs as is the
account that store belongs to.

**The four sizing variables decide what the project is charged**, and
they are deliberately here rather than in a step. A procedure able to
name its own node count could spend an allocation while reading like any
other step.

## Where a step's settings come from

A process step names a setup rather than carrying settings, so a hundred
runs with one setup repeat nothing and the record says which setup each
one used. The keeper holds the setups, seeded from the beamline's
register, and locks in the revision a run uses when it dispatches the
execution. The conductor reads that revision with the work and hands the
engine its settings with the step's override already written over them,
so no host holds a copy of a setup.

An execution dispatched before the keeper locked setups in carries none,
and so does one sent by a keeper that predates them. Those steps are
processed by a configuration this deployment holds, named by the same
`config`, which is what `CORA_COMPUTE_CONFIGS` is for. A deployment
whose steps all arrive with a setup sets no file. Each configuration is a
table:

```toml
[config.tomocupy-19bm]
reconstruction-type = "full"
reconstruction-algorithm = "fourierrec"
rotation-axis = 1628.5
energy = 92.0
pixel-size = 3.44
```

A step may override a setting its configuration holds, and only those:
an override of anything else is refused before it is submitted, which
is what catches a misspelt setting and what keeps every setting a run
used written down in some configuration. A setting a run needs belongs
in its configuration first.

`file-name`, `out-path-name` and `logs-home` are refused here, because a
run works them out: the input inside its place, the output folder inside
the same place, and a `logs` folder inside the output.

## Places on the compute host

A place is the folder a move lands data in, seen from the compute host.
`CORA_COMPUTE_PLACES` lists them, `alcf=/folder/on/the/host`, and a step
names one with `at`. Every place has to sit inside `BIND_SOURCE`, because
the container sees nothing else; one outside it stops the engine being
built rather than producing jobs that cannot find their input.

## Container paths and host paths are not the same path

The reconstruction runs inside a container with `BIND_SOURCE` bound to
`BIND_TARGET`, so everything tomocupy is handed is a container path
while the directories that must exist first are host paths. Places are
host paths, and the profile converts in both directions, which is why a
place outside `BIND_SOURCE` is refused at startup: there is no container
path to convert it to.

## What a handoff means here

A run can outlast the bound a walk waits for, and then the step ends
with a task id rather than with a result. That is a record of where the
work went, not a failure, and resolving it later is the watcher's job.

## What is not tested here

The submission path. Everything in `conductor.adapters.globus_process`
is covered against a double, because the adapter imports nothing and
needs no network. This file does need one, plus a credential and an
allocation, so what it does is checked by running it rather than by the
suite. Keep the logic here thin for that reason: anything worth a test
belongs on the other side of the seam.
