# Conducting

*What a conductor does at a beamline, what it guarantees, and what it refuses
to guarantee.*

## The job

A conductor is a program that runs at one beamline. It asks the record what
work has been approved there, takes one job, drives it step by step through
whatever hardware and run software the site has installed, reports each step as
that step ends, and asks again.

```
                          the beamline
      +--------------------------------------------------+
      |                                                  |
      |     motors, shutters,           a run engine,    |
      |     detectors                   where there      |
      |            ^                    is one    ^      |
      |            |                              |      |
      |            +--------  conductor  ---------+      |
      |                           |                      |
      +---------------------------|----------------------+
                                  |
                                  |  every call goes out
                                  v
                              the record
```

It runs at the beamline rather than in a data centre, because the protocols
that reach motors work only on the local network. Nothing calls in. A conductor
opens every connection it uses, which is what lets one record serve beamlines
it cannot reach.

## One walk, end to end

A walk is one traversal of one job. Here is the whole of it.

```
   ask what is waiting for this beamline    nothing is reserved for whoever
                                            read it, and two conductors may
                                            see the same job

   say this conductor is driving it         whichever wins the race earns
                                            the means of reporting on it

   for each step, in order:
       take a hold on what it names         refused if something else is
                                            already holding it
       drive it                             a value sent to a device, or a
                                            routine handed to an engine
       let the hold go
       say how the step ended               reaches the record now, rather
                                            than at the end of the walk

   say nothing further is coming            closes the record
```

The walk is in order and stops at the first step that does not finish, because
each step was written on the assumption that the one before it worked.

Four words for how a step ended:

```
   Done      the call returned without an error
   Refused   something else holds the hardware the step names
   Broken    the call raised
   Skipped   the walk had already stopped before reaching this step
```

Steps the walk never reached are reported as skipped rather than left out, so
the record shows the whole job and where it stopped:

```
   [ Done ][ Broken ][ Skipped ][ Skipped ]
               ^
               stopped here, and said so about the rest
```

### Two kinds of step

A **set** sends one value to one device. The step names that device, so what to
hold is derivable from the step itself, and nothing is opened that outlives it.

A **run** hands a named routine to an engine. What the routine touches is
inside the routine, so a run has to declare the devices it needs, and a run
declaring none is refused where it is composed rather than at the beamline. A
run also produces a second account of itself, which arrives by a different
road.

### Who records where the data went, and why it is not this

Not a conductor. A conductor did this once, for engines that answered with
a location rather than a name, on the reasoning that it was already holding
the address and nothing needed resolving.

What that reasoning missed is that nothing needed resolving for the watcher
either. Something standing beside such an engine reads the same value from
the same place, so the two were not splitting the work by which of them
could answer. Both could, both did, and a beamline running both recorded one
address twice against one step.

The line that replaced it is whether driving is required to know a thing:

```
   how a step ended under its own claim     needs the walk    the conductor
   what the engine said about the run       needs watching    whatever watches
   where the data was put                   needs watching    whatever watches
```

A conductor still cannot tell whether anything covers its beamline, and still
does not ask. The difference is that it no longer answers half the question on
the grounds of being nearby.

## What it promises

**The record of a walk outlives the walk.** Each step is reported as it ends
rather than batched at the finish, so a conductor killed outright leaves behind
every step that finished. This is checked by killing one with a signal the
process cannot catch. A test double that raised where a signal would land would
be checking that the code handles an exception, which is a different question
from whether anything is on disk when no code ran at all on the way out.

**A step's own outcome and the engine's account of it stay apart.** A conductor
reports a run the moment the engine returns. Whatever watches that engine
relays the engine's view on its own schedule, as a separate program. Nothing
orders the two, so a step can be done with no engine account at all, and the
two can disagree once both arrive. They stay two fields rather than one for
exactly that reason: the record keeps both rather than picking a winner between
two claims it cannot check.

**Two steps of one walk never collide.** A walk runs its steps in order and
each gives back what it held before the next one asks, so it is the ordering
that makes this true and not the hold. Worth saying plainly, because the hold
is what looks like it is doing the work.

**The hold is for whatever else shares the ledger.** Before a step runs it
takes a hold on the devices that step names, and a step whose devices are held
is refused rather than queued. A caller told which job holds the device can go
and do something else, where a queue would only make it wait. One conductor
walking one procedure at a time never reaches that refusal: it is there for a
process that embeds a walk beside something else holding the same ledger,
which is why the ledger is handed in rather than made.

The hold names the records a control system serves, and not the objects a
control library builds from them. Two objects built from one motor share no
keys at all, so two holds derived from them look unrelated while naming the
same hardware. [Architecture](architecture.md) carries the measurement that
settled this, and why sending a value and waiting on it is not enough.

## What it refuses to promise

**That a step worked.** Done means the call returned without raising. A scan
whose data was corrupted can still come back reporting success, so a word here
meaning it did what it meant to would be the overclaim that produces confident
wrong data.

**That the hardware stops when the walk stops.** A driver was killed mid-move
once and the motor travelled to its target with nothing alive that had asked
for it, and no record of a stop anywhere. A signal the process cannot catch
offers no hook, so no arrangement above the hardware can promise this. Anything
that must stop on abandonment needs a watchdog beside the hardware, which is
neither this program nor the record.

**That a walk survives its own restart.** What survives is what the walk did,
not the walk. Nothing is resumed and nothing is retried, because resuming would
mean starting the next step on a beamline nobody observed. Reading the hardware
back and comparing it against what the job expected is the stronger answer, and
it needs a reconcile step per device that nothing offers today.

**That the record closes itself when a conductor is killed.** This is the gap in
the promise above, and the two endings are worth drawing side by side because
they do not look alike:

```
   the walk stops at a failure
   [ Done ][ Broken ][ Skipped ][ Skipped ]    and the record is closed

   the conductor is killed
   [ Done ][ Done   ][    ?    ][    ?    ]    and the record is not
```

Everything confirmed before the kill stands. The step in flight was never
reported, nothing writes an outcome for the steps after it, and no ending is
recorded, so the job stays open on the record with nothing driving it. Finding
those is a question somebody puts to the record, asking which jobs have been
claimed for longer than anything at this beamline plausibly takes. It is not
something a conductor can answer about itself once it is gone.

**That two programs cannot drive one device.** The hold lives inside one
conductor and lasts as long as that conductor runs. It arbitrates the steps of
the walks that one program is driving, and it reaches nothing else: a second
conductor at the same beamline, or a scientist at their own session, is
invisible to it and to the record. Arbitrating across programs needs somewhere
durable to keep the holds, and nothing keeps them today.

**That a walk can be stopped partway through a step.** There is no interruption
point inside one. A device move waits for arrival in a loop of its own, and a
routine handed to an engine runs to the engine's own end, so a request to stop
lands between steps and a step already running finishes or times out on its own
terms.

## Where it stops

A conductor drives hardware and reports what it did. Four things on the other
side of that line belong to somebody else:

```
   what may be run, and by whom       the record
   what a routine does inside         the engine, or the site's own software
   whether the science worked         whatever reads the record afterwards
   stopping hardware on abandonment   a watchdog beside the hardware
```

It is a client of the record and not a part of it, and the arrow points one
way: a conductor dials out, and nothing ever dials in.

[Running one](running.md) covers what a deployment has to supply and what a
stop or a kill leaves behind. [Contract](client-contract.md) covers what a
client may rely on at these edges. [Glossary](glossary.md) pins each word
shared with the record.
