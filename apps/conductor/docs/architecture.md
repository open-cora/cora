# Architecture

How this package is put together, what each piece is for, and which decisions
came from driving real hardware rather than from reasoning.

## The rule

The part that decides things knows about nothing outside itself.

`claims`, `procedure`, `seams`, `conduct` and `outcomes` import the standard
library and each other, and nothing else. So putting a job together and working
out what it may touch needs no beamline software installed, and both are
testable without any. Everything that talks to the outside world lives under
`conductor/adapters/` and is named in exactly one place, the entry point that
picks it.

That is checked by `tests/test_the_core_names_no_seam.py` rather than promised
here.

## The pieces

```
   the part that decides
   ---------------------------------------------------------------
   procedure.py            claims.py             seams.py
     Set     one record       Scope                 Adjusting
             one value        Claim                   set
     Run     ask an engine    Ledger                Running
             to run a routine   acquire               run
     Procedure                  release             Tasking
       an ordered list                                take, claim
                                                    Reporting
                                                      step ended
                                                      walk ended
           \                    |                     /
            +-----------> conduct.py <---------------+
                            one step at a time,
                            holding its claim
                                 |
                                 v
                            outcomes.py
                              Done Refused Broke Skipped

   the parts that know one outside system each
   ---------------------------------------------------------------
   adapters/epics_control.py          drives records over EPICS
   adapters/bluesky_engine.py         runs a plan on an engine
   adapters/keeper_http.py            talks to the record over HTTP

   in between, knowing neither a job nor a system
   ---------------------------------------------------------------
   config.py     three settings, and how to build an engine
   intake.py     take a job, claim it, walk it, ask again

   Nothing above imports anything below, including the two in the middle.
```

A `Set` works out for itself which hardware it touches: it names one record, so
that record is the claim. A `Run` cannot. Which devices a routine touches is
inside the routine, and what an engine reports afterwards describes one run rather
than the routine, so there is nothing to work it out from. A run step
that declares nothing is refused where it is built, because the alternative is a
job whose most dangerous step claims the least.

## One walk, step by step

```
   ask what is waiting for this beamline        Tasking.take
   say this conductor is driving it             Tasking.claim
     which hands back the way to report on it
   for each step, in order:
       take a hold on the hardware it names     Ledger.acquire
       drive it                                 Adjusting or Running
       let the hold go                          Ledger.release
       say how it ended                         Reporting.step_ended
   close the record                             Reporting.walk_ended
```

The walk is in order and stops at the first step that does not finish. Steps it
never reached are reported as skipped rather than left out, so the record shows
the whole job and where it stopped.

Each outcome goes out as it happens rather than as a batch at the end. Whether a
run of them is worth one call each depends on how a particular deployment
records things, and deciding that inside the loop would put one deployment's
costs in everybody's path.

A failure to record is not caught. An adapter that means to carry on while
nothing can be told handles its own outage, which keeps the degraded case a
deployment's question rather than this loop's. It also sits outside the part
that produces a broken outcome, because a set that arrived and could not be
reported did not break.

## Why the hold is on record names, not on device objects

This is the decision the package is built around, and it came from a
measurement rather than a principle.

A real scan was driven over a real motor while a second process wrote to the
same motor. Four collisions, and all four runs finished reporting success. One
recorded four of its six points at a single position in two seconds. One
silently moved a point and left a record that agrees with itself. One left a
field latched so the next run would break too. The same write aimed at a motor
the scan did not own changed nothing at all.

So the hazard is two writers on one device, neither can see what the other
holds, and nothing downstream catches it afterwards.

**The hold names records, and not the objects a control library builds.** Two
objects built from one motor share no read keys at all, so two holds derived
from them look unrelated while naming the same hardware. Worse, a blocking move
through the second one returns before the motion starts. The record name is what
the control system serves and the only vocabulary two clients that have never
met can agree on. The description field does not qualify: served empty, writable
by anyone, unique by nothing.

**And covering is not a string prefix.** `2bmb:m1` and `2bmb:m10` are two
motors. A record covers itself and nothing else; a namespace is written with its
trailing separator and covers what is beneath it.

## What the hold does not do

It does not police one walk against itself. A walk runs in order and each hold
is let go as its step ends, so no two steps of one job are ever held at once and
none of them can collide. The refusal bites between holders: two walks handed
the same ledger, or a walk started while something else has already taken a
motor.

That is the arrangement rather than a gap, and it is why the walk is handed a
ledger rather than making one. It is also single-threaded: the ledger checks and
then writes without a lock, which is sound while one thread walks at a time and
is the first thing to change if steps ever run in parallel.

## The control adapter, and why a put is not enough

Sending a value and waiting would be the obvious implementation, and it is not
enough, because two of the three corruptions above are reachable through one.

```
   a rival write to the value       redirects the motor, and the completion
                                    that comes back belongs to the rival
   the stop field set to Stop       holds the motor, and every later move
                                    returns at once having done nothing
```

So the adapter refuses a record whose stop field is not set to go, it waits on
the readback rather than on the write, it waits for the motion-done field to say
the motion finished, and it reports which of those it managed. A record serving
no readback is confirmed against itself, which proves the write landed and
nothing more, and says so rather than implying otherwise.

**Position alone was not enough, and that was measured too.** Waiting only on
the readback let the rival case through: a motor redirected past its target
crosses the tolerance window on the way, so a check looking only at position can
catch it in transit and call that arrival. Against a simulated control system, a
move to 3.0 with a rival redirecting to 9.0 mid-flight came back as arrived at
three of four tolerances, every time with the motion-done field still reading
not done. The walk would then have let the hold go and started the next step
against a motor still travelling.

Arrival is two conditions now. The suite has a paired test that makes the point:
the same move succeeds undisturbed and fails when a rival redirects it
mid-flight, with the same settle time on both, so the failure cannot be a
timeout dressed up as a finding.

## What is deliberately not an object

**A queue.** A step whose hardware something else holds is refused, and the
refusal names the holder. A caller told that can go and do something else, which
is the better answer for the kind of caller this has.

**A retry.** Nothing here decides that a failed step is worth another go. What
failed and why goes on the record, and whatever reads the record decides.

**A judgement about the science.** A finished step means the call returned
without an error. Nothing here opens a result.
