# What breaks, and what the record knows

*Four findings from driving the deployment into failure on purpose, at a
beamline where nothing could move. One has since been measured to the point
of being fixed. The rest are open questions rather than defects with an
obvious fix, and this page is where the options are weighed before anybody
picks one.*

## How these were found

Beamlines were wired to simulators serving records this system supplies
itself: motors and a scan server on the beamline's own IOC host, on search
ports that production discovery does not use. Two carried that arrangement
when these findings were taken, and all four carry it now. With that in
place a conductor can be killed, an engine can be stopped, and two
dispatches can be raced, without anything on the floor moving.

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

## A conductor goes blind for a while after a long engine outage

Restart an engine and the conductor driving it keeps failing with
`UnreachableEngineError` for a time, while a fresh client on the same host
reads the same record immediately. How long depends on how long the engine
was away:

| engine absent for | channel reconnected |
| --- | --- |
| 2.5 seconds | at once, as soon as the server was back |
| about 10 seconds, channel created during the outage | 3.5 seconds after it returned |
| 3 minutes | **65 seconds after it returned** |

This is Channel Access search backoff, not a defect in anything here. A
client that cannot resolve a channel retries on a widening interval, capped
by `EPICS_CA_MAX_SEARCH_PERIOD`, which defaults to 300 seconds. The longer a
server stays away, the further out the next search is scheduled, so the
client does not notice its return for up to that period. A brand new client
searches at once, which is why `caget` succeeds while the long running
process does not.

**The operational shape is what matters.** An IOC restart is ordinary. A
conductor that refuses every dispatch for the next minute, or for the next
five after a longer outage, is not, and the symptom points at the control
system rather than at the client, so the first stretch of diagnosis goes to
the wrong place. Restarting the conductor clears it, which makes it look
like a conductor bug, and it is not.

**An earlier version of this page said a conductor never reconnects.** That
was drawn from one episode of about seventy seconds that happened to follow a
long outage, and it did not survive measurement: the same conductor
dispatched normally after a short stop and start. The claim was stronger than
the evidence, and the measured version above is both weaker and more useful.

### What bounds it, and what only looks as though it would

Three things could have bounded this. One of them does.

**Capping the search period** with `EPICS_CA_MAX_SEARCH_PERIOD` has a floor
of 60 seconds, so it turns a possible five minute blind spot into a one
minute one and does nothing at all for the case measured above. One line of
configuration, and almost no help.

**Building another channel for the same name does nothing**, which is the
opposite of what this page assumed when it first suggested it. The library
keeps one channel per name per process, so asking for a name it already
knows hands back the same unresolved channel, carrying the same widened
schedule. With the server back and answering, a second channel for the name
was still unconnected thirty seconds later. Disconnecting the old one first
does not change it either: disconnecting drops the wrapper and leaves the
library's entry for the name behind.

**Clearing the channel is the one that works**, and it is one call. With the
server back for eighteen seconds and the held channel still blind, three
questions asked in the same process in the same instant:

| asked for | answered in |
| --- | --- |
| the channel held across the outage | still waiting |
| a name this process had never searched for | 0.0 seconds |
| the same name, cleared and built again | 0.0 seconds |

The middle row is a control and it is what makes the other two mean
anything. It shows the server was answering new searches at that moment, so
the held channel was waiting on its own schedule rather than on anything
still starting up.

**This one is fixed.** A channel the engine was holding that no longer
resolves is cleared and built again, so the dispatch after an engine restart
reaches the server instead of waiting out an interval that grew while nobody
was asking. A channel that never connected in the first place is still a
refusal, because the rebuild is for a channel that outlived its server and
not a retry against a server that is not there.

What the suite can show of this is narrower than what the beamline showed.
Against a live soft IOC a channel cannot be made genuinely unresolvable, so
the test holds the engine to rebuilding rather than refusing, and the
measurement above is the only evidence that clearing is the part that makes
the rebuild reach anything.

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

The first two are the same shape: **a process that stops is handled, and a
process that stops partway through is not.** Supervision restarts things, and
nothing reconciles what they were doing when they died. The record is where
that gap becomes visible, which is why the most useful work is making the gap
findable before it is making it impossible.

The reconnection one is a different lesson, and a cheaper one. It looked like
a defect in this system, it was a documented property of the protocol
underneath, and the thing that separated those two readings was a probe that
took four minutes. The first write up of it here asserted the stronger and
wrong version, and the repair this page then proposed was wrong too, in the
same way: stated confidently, resting on an unmeasured assumption about what
the library does, and refuted by the first measurement that asked. Both
times the probe was minutes and the prose was already written.

That is the argument for the simulators rather than for any one of these
findings. Each correction came from being able to stop a server and start it
again on a schedule, which is not a thing anybody can do to a beamline that
is running experiments.
