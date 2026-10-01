# Architecture

*How this package is put together, what the core is not allowed to know, and
which decisions came from driving real hardware rather than from reasoning.*

[Conducting](conducting.md) says what a walk promises, in no code at all. This
page is the same walk with the names on it, for somebody about to change one.

## The rule

**The part that decides knows about nothing outside itself.**

Six modules import the standard library and each other, and nothing else:
`claims`, `confinement`, `procedure`, `seams`, `conduct` and `outcomes`. So
composing a procedure and working out what it may touch needs no beamline
software installed, and both are testable without any. Everything that speaks
to an outside system lives under `conductor/adapters/` and is named in exactly
one place, the entrypoint that picks it.

`tests/test_the_core_names_no_seam.py` holds that rule, and it pins the
membership as well: `EXPECTED_CORE_MODULES` fails when a module joins or leaves
the core without the test being told, so the list above cannot quietly stop
being the list.

## The pieces

```
   the core: six modules, the standard library, and each other
   ---------------------------------------------------------------------
   procedure.py              claims.py            seams.py
     Set    one record         Scope                Adjusting   set
            one value          Claim                Running     run
     Run    a routine on       Ledger               Tasking     take
            an engine            acquire                        claim
     Procedure                   release            Reporting   step_ended
       an ordered list                                          walk_ended
                                                    Filing      record

   confinement.py                                 outcomes.py
     which records this deployment                  Done     Refused
     may write, and the control seam                Broke    Skipped
     that holds it to them

              \                    |                     /
               +-----------> conduct.py <---------------+
                               one step at a time,
                               holding its claim

   the adapters: one outside system each
   ---------------------------------------------------------------------
   adapters/epics_control.py      drives records over Channel Access
   adapters/bluesky_engine.py     hands a plan to an engine in process
   adapters/tomoscan_engine.py    drives a scan server over its records
   adapters/http_tasking.py       takes work and reports, over HTTP

   in between, knowing neither a procedure nor an outside system
   ---------------------------------------------------------------------
   config.py     the settings, and how to build an engine
   intake.py     take, claim, walk, ask again

   Nothing above imports anything below, the two in the middle included.
```

A `Set` works out for itself which hardware it touches: it names one record, so
that record is the claim. A `Run` cannot. Which devices a routine touches is
inside the routine, and what an engine reports afterwards describes one run
rather than the routine, so there is nothing to work it out from. A run step
that declares nothing is refused where it is built, because the alternative is
a procedure whose most dangerous step claims the least.

Two engine adapters rather than one is the point rather than an accident.
`bluesky_engine` calls a callable in this process; `tomoscan_engine` connects
to a service on the control network and writes to its records. The seam they
both satisfy is `Running`, and nothing above them can tell which is installed.

## One walk, in code

```
   intake
     Tasking.take(beamline, wait) ............... Assignment, or None
     Tasking.claim(execution_id) ................ Reporting, or None
     conduct(procedure, adjusting=, running=, reporting=, filing=, cites=)
         |
         |  for index, step in enumerate(procedure.steps):
         |
         |      stopped already?   Skipped(step=...)
         |
         |      otherwise          Ledger.acquire, held for the block
         |                             holder is f"{procedure.name}[{index}]"
         |                         Adjusting.set(record, value)        a Set
         |                         Running.run(routine, params, cites) a Run
         |                         Ledger.release
         |                         -> Done | Refused | Broke
         |                         stopped = not isinstance(outcome, Done)
         |
         |      Reporting.step_ended(index, outcome)
         |      Filing.record(cites, address)     after the report, never
         |                                        before it
         |
         |  Reporting.walk_ended()
         v
     Walk(procedure, outcomes, unfiled)
```

Each outcome goes out as it happens rather than as a batch at the end. Whether
a run of them is worth one call each depends on how a deployment records
things, and deciding that inside the loop would put one deployment's costs in
everybody's path.

**Filing comes after the step report and not before it.** The report is what
the record is owed; the address is an extra this walk can offer, and a slow or
failing catalogue must not delay the first. A filing that fails does not fail
the step either: it comes back in `Walk.unfiled` rather than changing what the
step is recorded as having done.

A failure to record is not caught here. An adapter that means to carry on while
nothing can be told handles its own outage, which keeps the degraded case a
deployment's question rather than this loop's. It also sits outside the part
that produces a broken outcome, because a set that arrived and could not be
reported did not break.

## What each decision cost

Three of these came from driving real hardware, and the measurements are the
reason they are not arguable.

### The hold names records, not device objects

A real scan was driven over a real motor while a second process wrote to the
same motor. Four collisions, and all four runs finished reporting success. One
recorded four of its six points at a single position in two seconds. One
silently moved a point and left a record that agrees with itself. One left a
field latched so the next run would break too. The same write aimed at a motor
the scan did not own changed nothing at all.

So the hazard is two writers on one device, neither can see what the other
holds, and nothing downstream catches it afterwards.

The hold names records and not the objects a control library builds. Two
objects built from one motor share no read keys at all, so two holds derived
from them look unrelated while naming the same hardware, and a blocking move
through the second one returns before the motion starts. The record name is
what the control system serves and the only vocabulary two clients that have
never met can agree on. The description field does not qualify: served empty,
writable by anyone, unique by nothing.

Covering is not a string prefix either. `2bmb:m1` and `2bmb:m10` are two
motors. A record covers itself and nothing else; a namespace is written with
its trailing separator and covers what is beneath it.

**What the hold does not do** is police one walk against itself. A walk runs in
order and each hold is released as its step ends, so no two steps of one
procedure are ever held at once. The refusal bites between holders: two walks
handed one `Ledger`, or a walk started while something else has already taken a
motor. That is why `conduct` is handed a ledger rather than making one. It is
also single-threaded, checking and then writing without a lock, which is sound
while one thread walks at a time and is the first thing to change if steps ever
run in parallel.

### Arrival is two conditions, not one

Sending a value and waiting would be the obvious control adapter, and it is not
enough, because two of the three corruptions above are reachable through one.

```
   a rival write to the value       redirects the motor, and the completion
                                    that comes back belongs to the rival

   the stop field set to Stop       holds the motor, and every later move
                                    returns at once having done nothing
```

So the adapter refuses a record whose stop field is not set to go, it waits on
the readback rather than on the write, it waits for the motion-done field to
say the motion finished, and it reports which of those it managed. A record
serving no readback is confirmed against itself, which proves the write landed
and nothing more, and says so rather than implying otherwise.

Position alone was measured and was not enough. A motor redirected past its
target crosses the tolerance window on the way, so a check looking only at
position can catch it in transit and call that arrival. Against a simulated
control system, a move to 3.0 with a rival redirecting to 9.0 mid-flight came
back as arrived at three of four tolerances, every time with the motion-done
field still reading not done. The walk would then have released the hold and
started the next step against a motor still travelling.

The suite has a paired test that makes the point: the same move succeeds
undisturbed and fails when a rival redirects it mid-flight, with the same
settle time on both, so the failure cannot be a timeout dressed up as a
finding.

### Nothing is writable by default

An empty `confinement` refuses every set. That is the useful default rather
than the comfortable one: a configuration that forgot to say what may be
written looks exactly like one at a beamline with nothing to write, and reading
both as everything turns an omission into a conductor that can drive hardware.
A deployment says what it may touch, or it touches nothing.

The engine seam never had this gap, because an engine is configured with a
prefix and pointing a deployment at a station's real acquisition server is a
deliberate edit of one setting. This is the same guarantee for the seam a step
names directly.

## What is deliberately not an object

**A queue.** A step whose hardware something else holds is refused, and the
refusal names the holder. A caller told that can go and do something else,
which is the better answer for the kind of caller this has.

**A retry.** Nothing here decides that a failed step is worth another go. What
failed and why goes on the record, and whatever reads the record decides.

**A durable ledger.** `Ledger` argues its own non-durability and the argument
holds: one that survived a restart would claim to know something it does not,
because the hardware kept moving after the process died.

**A judgement about the science.** A finished step means the call returned
without an error. Nothing here opens a result.
