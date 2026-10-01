# What breaks, and what the record knows

*Four findings from driving the deployment into failure on purpose, at a
beamline where nothing could move. Three of them are open questions rather
than defects with an obvious fix, and this page is where the options are
weighed before anybody picks one.*

## How these were found

Two beamlines were wired to simulators serving records this system supplies
itself: motors and a scan server on the beamline's own IOC host, on search
ports that production discovery does not use. With that in place a conductor
can be killed, an engine can be stopped, and two dispatches can be raced,
without anything on the floor moving.

That arrangement is worth stating because it is the reason these answers
exist. Every one of them is about what happens when a process dies partway
through, and none of them could be asked of a beamline running experiments.

## A driver that dies strands its execution and loses the data

Killing a conductor five seconds into a scan leaves this:

```
  the engine      keeps scanning, finishes, writes its file
  the supervisor  returns the conductor in fifteen seconds
  the conductor   comes back and asks for new work
  the record      the execution is still Claimed, with no step outcome
```

Nothing is wrong with any single part. The engine was never told to stop. The
supervisor did what a supervisor does. The conductor has no memory across a
restart and so has nothing to resume. The record is the only place the
inconsistency lands, and it lands as an execution that will sit `Claimed`
until somebody looks.

**The data is the sharper half.** A scan ran to completion and produced a
file, and no dataset was registered for it. The run happened; the record says
it never finished starting.

## The one view built to find that cannot see it

`list_steps_without_datasets` exists to answer which runs produced data
nobody filed. Its query is:

```sql
WHERE engine_reference IS NOT NULL
  AND dataset_id IS NULL
```

An engine reference is written when a step is **reported**. A driver that
died reported nothing, so the step carries no reference, so the run is
invisible to the view. There are two classes of unrecorded data and the
record has a view for one:

| | what it looks like | found by |
| --- | --- | --- |
| the step was reported and nothing was filed | an engine reference, no dataset | the existing view |
| the driver died before reporting | no reference, execution stuck `Claimed` | nothing |

The second class is the one where the keeper does not know anything happened,
which is also the one where a file exists on a beamline filesystem with no
owner in the record.

### What could close it, and what each costs

**Widen the query.** Add steps whose execution has been `Claimed` without
progress for longer than some interval. Cheap, and it changes the meaning of
the view from "data we failed to file" to "places the record may be
incomplete", which is arguably the question somebody actually has before an
audit.

**A separate view for stranded executions.** Keeps the two questions apart,
which matters because they have different answers: one is fixed by filing a
dataset, the other by deciding what happened to a walk. Costs a second slice
and a second permission.

**Neither, and accept it.** Defensible only while every execution is watched
by somebody, which is the condition this system exists to remove.

## A staleness view is already possible, and does not exist

`proj_execution_execution_summary` carries no claim timestamp, so the obvious
objection is that nothing records when a walk began. It carries `updated_at`,
which moves when the status changes and again on every step report, so

```sql
WHERE status = 'Claimed' AND updated_at < now() - <threshold>
```

finds abandoned walks today, with no migration.

**Its blind spot is the case that matters most.** A procedure of one long step
refreshes nothing between its claim and its report, so a legitimate two-hour
tomography scan is indistinguishable from a conductor that died in the first
minute. The threshold has to exceed the longest honest step, which at a
tomography beamline makes the view slow to notice exactly the runs worth
noticing.

That is the argument for a heartbeat rather than against the view. A walk that
said "still mine" on an interval would separate the two, and a view built on
`updated_at` would keep working unchanged if one arrived. Starting with the
view costs nothing that a heartbeat would waste.

**An expiring claim was considered and refused.** A claim that lapses on its
own turns one failure into two, because the original conductor may still be
driving, and nothing here can tell a dead one from a slow one. Whatever
notices staleness should report it rather than act on it.

## A conductor survives an engine restart as a process, not as a client

Stop a simulated engine and start it again, and every later dispatch from the
conductor that was already running fails with `UnreachableEngineError`, while
a fresh client on the same host reads the same record immediately. Measured
still failing after thirty seconds and two dispatches. The only recovery found
was restarting the conductor.

This is the finding with the shortest path to biting a real beamline. An IOC
restart is ordinary. A conductor silently unable to reach it afterwards is
not, and the symptom points at the control system rather than at us, so the
first hour of diagnosis goes to the wrong place.

What it is not yet is understood. `TomoscanEngine` keeps one channel per
record for the life of the process and asks each one to connect before use,
and whether the stale channel is never re-searched, re-searched too slowly, or
abandoned by the client library is unmeasured. The options differ by which of
those is true:

- **Rebuild the channel on a failed connection** rather than reusing a cached
  one. Smallest change, and wrong if the library would have recovered given
  longer, because it would mask a timeout that should be tuned.
- **Exit on an unreachable engine** and let the supervisor restart the
  process, which is known to recover. Blunt, and it converts a per-dispatch
  failure into a restart loop at a beamline whose IOC is genuinely down.
- **Leave it and document it.** Honest only if the diagnosis says the client
  does recover and the measured thirty seconds was simply not long enough.

The measurement comes first, and it is cheap: hold a channel open, restart the
server, and watch how long reconnection actually takes.

## A scan has no bound a deployment can set

`scan_timeout` defaults to one hour and the conductor's entrypoint constructs
its engine without passing one, so no configuration can change it. It has not
bitten, because a disconnected engine is caught by connection failure long
before the timeout matters.

It is recorded here rather than fixed because the trigger is missing. A
beamline whose scans legitimately exceed an hour, or one that wants a walk
abandoned sooner than that, is the thing that would say what the right shape
is. Adding a setting before either exists would be guessing at a default
twice.

## What these share

Three of the four are the same shape: **a process that stops is handled, and
a process that stops partway through is not.** Supervision restarts things,
and nothing reconciles what they were doing when they died. The record is
where that gap becomes visible, which is why the most useful work here is
making the gap findable before it is making it impossible.
