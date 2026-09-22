# Findings

What a conductor holding both a control seam and an acquisition seam
actually does to a scan, and what it leaves behind when it dies.
Everything below is from `collisions.json` and `orphan.json`, produced by
the two scripts here, not from reading documentation.

Run against bluesky 1.15.1, ophyd 1.11.2, caproto 1.3.0, Python 3.13.

## The short version

**Every collision reported success.** Four rival writes during a scan,
four runs ending `exit_status: "success"`, no exception, no `reason`.
Three of the four landed on the scanned motor and each corrupted the run
a different way. At the surface a reporter watches, all three are
indistinguishable from the clean baseline, so all three arrive in AROC as
Completed runs.

**The three corruptions are not equally detectable, and the most
damaging is the most invisible.** A rival move leaves setpoint and
readback disagreeing in the data, which something could check. A rival
stop leaves them agreeing at a position nobody asked for, which nothing
downstream can catch, because what was asked for lives in the plan and
never reaches the record.

**One of them outlives the run.** `.SPMG` set to Stop is sticky, exactly
as `AbortScan` is in the TomoScan spike, so the next scan of that motor
is broken too until something writes Go.

**Harm is device-scoped.** The same write aimed at a motor the scan does
not own changed nothing. So the boundary that matters is not control
against acquisition, it is who owns this device right now, and the four
ports in the sketch do not draw it.

**A device claim has to key on the PV prefix, not the ophyd object.** Two
objects bound to one motor share no read keys at all, so two claims can
be disjoint by inspection and name the same hardware. Worse, a blocking
move through the second one returns before the motion starts. The one
facility-side label on the record, `DESC`, is served empty and writable
by anyone.

**Hardware outlives the conductor.** SIGKILL mid-move, and the motor
drove itself the rest of the way with nothing alive to command it. No
stop document was ever emitted, so a run uid exists that nothing will
ever close.

**A conducted run can carry an identity at genesis after all.** A bare
RunEngine hands the caller nothing at submit time, but it will carry an
id the caller mints, verbatim, into the start document. That is one model
change Execution does not have to make.

## 1. Four rivals, four successes

The scan is `scan([det], mtr1, 0, 5, 6)`, about five seconds at velocity
1.0. The rival is a separate process doing one `caput` roughly 1.7
seconds in. `det` is a simulated detector computing its value from the
motor's position, so the numbers in the last column are what the data
would say.

```
   scenario        seconds  exit_status  events  position after
   undisturbed         5.1  success           6            5.0
   rival_move         16.1  success           6         4.1111
   rival_stop          5.3  success           6            5.0
   rival_hold          2.1  success           6         1.6667
   other_device        5.2  success           6            5.0
```

Six events every time. `exit_status: "success"` every time. Nothing
raised into the RunEngine and no `reason` was set on any stop document.

The `seconds` column is the only field in that table that distinguishes
the three bad runs from the two good ones, and reading it requires
knowing how long the scan should have taken, which is a fact about the
plan and the devices rather than anything on the record.

## 2. `rival_move`: wrong data, and the rival's own value in the record

A write of 9.0 to `.VAL` while the scan owned the motor.

```
   asked   got      det
     0.0   0.0    4.3937
     1.0   1.0   32.4652
     9.0   2.1014  92.3651   <- asked is the rival's value, not the scan's
     3.0   8.8983     0.0
     4.0   3.1111  82.9669
     5.0   4.1111  27.3121
```

Two things are happening and they are worth separating.

**The recorded setpoint is the rival's.** ophyd reads `user_setpoint`
from `.VAL`, and `.VAL` is a field any client can write. The scan asked
for 2.0; the rival overwrote the field; the event carries 9.0. So the run
records a request that nothing in the plan ever made.

**Every move after the collision completes at the wrong place.** The
motor record raises `.DMOV` when it finishes whatever move it is on, and
ophyd takes that as its own move completing, so from the collision
onward each point is read at wherever the motor happened to be. The run
ends at 4.1111 having been asked for 5.0, and the last four points are
off by between 0.9 and 5.9.

The detector column is what this costs. At the point labelled 3.0 the
detector read 0.0, because the motor was at 8.9 and out of the Gaussian
entirely. A dataset like this is not noisy, it is mislabelled, and it is
mislabelled in a way that looks like physics.

This is the detectable case. Setpoint and readback disagree in five of
six rows, so a check comparing the two would catch it. Nothing in this
stack performs that check by default.

## 3. `rival_stop`: one point moved, and the record agrees with itself

A write of 1 to `.STOP`.

```
   asked    got
     0.0    0.0
     1.0    1.0
     1.5556 1.5556   <- the scan asked for 2.0
     3.0    3.0
     4.0    4.0
     5.0    5.0
```

The motor record writes the current readback into `.VAL` when it is
stopped, so after the stop the setpoint field holds where the motor
actually is. The scan reads both, gets the same number twice, and
records a point that is internally consistent and is not the point it
asked for. The run recovers on the next move and finishes at 5.0 in 5.3
seconds against a 5.1 second baseline.

**Nothing downstream can catch this.** Setpoint equals readback, the
timing is normal, the point count is right, and the run reports success.
The only witness to the discrepancy is the plan's intended trajectory,
and the plan's arguments are not on the event and the scan's intent is
not in the record. This is the case that matters most for AROC, because
it is the one where the record is confidently and quietly wrong.

## 4. `rival_hold`: a six-point scan in two seconds, and it is sticky

A write of `Stop` to `.SPMG`, the field that holds a motor in place.

```
   asked    got
     0.0    0.0
     1.0    1.0
     1.6667 1.6667
     1.6667 1.6667
     1.6667 1.6667
     1.6667 1.6667
```

The motor stops accepting moves, so every subsequent move returns
immediately and the scan finishes in 2.1 seconds instead of 5.1. Four of
the six points are the same reading taken four times. `exit_status` is
`success`.

Then the reset step found `.SPMG` still holding:

```
   after rival_hold   spmg_found = "Stop"
   every other run    spmg_found = "Go"
```

Nothing put it back. This is the same shape the TomoScan spike found in
`AbortScan`, which "still reads 1 during the next scan", and it is the
second engine in a row where a stop signal is a latch rather than an
event. A conductor whose control seam can write a latch has to know
which fields latch, per device, and unlatch them, and there is no
general rule that tells it which those are.

## 5. `other_device` is the control, and it came back clean

The same write, the same timing, aimed at `mtr2`, which the scan does
not touch. The readings are identical to the undisturbed baseline to
four decimal places, and the run took 5.2 seconds against 5.1.

So none of the above is about concurrency, about Channel Access, or
about two processes talking to one IOC. It is about two writers and one
device. That distinction is the whole finding of this spike, because it
is not the distinction the port sketch draws.

## 6. The orphan: the motor finished the move by itself

The driver is a separate process running a real RunEngine over a real
EpicsMotor, sent SIGKILL three seconds into a three-point scan across
the motor's full travel.

```
   at the kill     readback 2.449   setpoint 5.0   moving 1   dmov 0
   +0.5s           readback 2.9592  setpoint 5.0   moving 1   dmov 0
   +1.0s           readback 3.4694  setpoint 5.0   moving 1   dmov 0
   +1.5s           readback 3.9796  setpoint 5.0   moving 1   dmov 0
   +2.0s           readback 4.4898  setpoint 5.0   moving 1   dmov 0
   +2.5s           readback 5.0     setpoint 5.0   moving 1   dmov 0
   +3.1s           readback 5.0     setpoint 5.0   moving 0   dmov 1
```

Two and a half seconds of motion with nothing alive that asked for it.
That is the motor record working correctly: a move is a request to a
controller, and the controller executes it whether or not the requester
is still there. Every real motor behaves this way.

The documents that reached the outside were `start`, `descriptor` and one
`event`. No stop, and there never will be one. The run's uid is known,
because the start document carried it before the kill, and it names a run
that can never be closed by the thing that started it.

**SIGKILL is the case that matters and it is the case with no hook.** A
conductor can catch SIGTERM and stop its devices, the way the reporter
drains its queue. It cannot catch SIGKILL, a power loss, or a kernel
OOM. So "the conductor stops the hardware when it dies" is not a promise
any conductor can make, and anything that must stop on abandonment needs
a watchdog on the IOC side. That is outside AROC and outside the
conductor, and it should be said out loud rather than assumed into one
of them.

## 7. A bare RunEngine will carry an id it is given

This was question two and it has a better answer than expected.

There is no handle at submit time: `RE(plan)` returns uids when the plan
is finished, and the engine mints the run's uid itself. But metadata
passed at the call rides into the start document unchanged:

```
   minted by caller    540aa3cb-1d6b-4aaa-97a1-e7f9832e376f
   in start document   540aa3cb-1d6b-4aaa-97a1-e7f9832e376f
   engine run uid      0e8d351c-ec26-4d05-ab46-51c7417b8745
```

So a conductor that mints an id before it submits holds a reference that
is in its hand at genesis and is on the engine's record afterwards, and
the two can be joined without the engine knowing anything about AROC.

That is the same move Counsel already settled for proposals, where the
agent submits with its own reference and resolves it later through
`GET /runs?external_ref_scheme=...`. It means Run's required
`external_ref` survives the conducted path: the conducted genesis carries
the conductor's directive id, and the engine's own uid arrives later as a
second reference or not at all.

One caveat on this section's method. The key list is diffed against a
`count` rather than a `scan`, so `motors`, `plan_pattern`,
`plan_pattern_args` and `plan_pattern_module` show as added and are
nothing but the difference between two plan shapes. `aroc_directive_id`
is the only key in that list that this spike put there.

## 8. Two objects, one motor, and a waited move that does not wait

Section 5 established that the hazard is two writers on one device. That
leaves the question of what a procedure step declares when it claims one,
and the obvious answer is the object a startup profile builds. It is
wrong, and `shared_device.py` measures what it costs.

`spikes/ophyd_adapter/` established the first half: an ophyd Device's
name and its extent are client-side opinions, because that spike built
one station under two names against one IOC and nothing rejected or
recorded it. This tree reproduces the same thing on a motor. Two
`EpicsMotor` objects, `station_sample_x` and `tomo_sample_x`, both bound
to `sim:mtr1`, both connected, and the keys they read under share nothing
at all:

```
   first_read_keys    station_sample_x, station_sample_x_user_setpoint
   second_read_keys   tomo_sample_x, tomo_sample_x_user_setpoint
   shared_keys        []
   same_underlying_pv True, sim:mtr1.VAL
```

Two declarations built from those objects are disjoint by inspection and
name one motor.

The second half is what that costs, and it is worse than a missed
refusal. The control is taken in the same process before the second
object exists:

```
   one object     move(1.0)  returned after 1.03s  at 1.0  arrived
                  move(5.0)  returned after 4.07s  at 5.0  arrived

   two objects    move(1.0)  returned after 1.03s  at 1.0  arrived
                  move(5.0)  returned after 0.00s  at 1.0  NOT arrived
```

A blocking move through the second object returned instantly with the
motor four seconds from its target, and the motor then travelled there
with the caller already past the call. `.DMOV` was high from the first
object's completed move, the second object's subscription had that value
cached, and its move status completed against it.

So a procedure that claimed devices by object would not merely fail to
refuse an overlapping step. Its own `wait` would stop meaning anything,
in a way that looks exactly like a fast move.

**The unit of exclusion has to be the PV prefix.** Two writers can only
be said to share something both can name, and the object's name is
whatever a startup profile passed as `name=`. The one facility-side label
on the record does not qualify either:

```
   DESC as served     ""
   after a write      "anything a client likes"
```

Served empty, writable by any client, and unique by nothing. The prefix
is what the IOC serves and what both clients resolve, and it is the only
identifier here that two parties who have never met will agree on.

## What this changes

**The four ports do not draw the boundary that matters.** A control seam
and an acquisition seam can each be correct and still produce section 2,
3 and 4, because the hazard is two writers on one device and neither port
knows what the other holds. What a procedure needs before it needs any of
the four is a claim on a device: a step declares what it touches, and
overlapping steps are refused rather than interleaved. That is a
conductor concern, not an AROC one, but it is the thing to design first
and it is not in the sketch.

**And the claim keys on the PV prefix.** Section 8 is the reason, and
`spikes/ophyd_adapter/` reached the same conclusion from the other side.
A claim over ophyd Device objects can be disjoint by inspection while
naming one motor, and the failure it admits is not just an unrefused
overlap but a blocking move that returns before the motion starts. The
prefix is the only identifier two parties who have never met will agree
on, since `DESC` is served empty and writable by anyone.

**AROC cannot see any of this, and a Procedure aggregate would not help.**
Three of four corrupted runs arrive as Completed. Adding an enactment
record in Execution would add a row saying the procedure's steps each
finished, which is true and useless, and it would look like an answer to
"did the procedure do what it said" when nothing in the system can answer
that. This is an argument for the definition-only Procedure and against
holding enactment state in AROC until something can check it.

**The fourth terminal question gets harder, not easier.** The TomoScan
spike asked for a terminal meaning "ended, outcome unknown". What this
spike found is different and worse: the engine says success and is wrong.
No terminal set fixes a confident wrong answer, so the fourth terminal
remains worth having for TomoScan's sake and does not address this.

**One model change is not needed.** The conducted genesis can carry an
`external_ref`, so the required-reference invariant in
`apps/api/src/aroc/execution/aggregates/run/state.py` survives conducting,
provided the reference is the conductor's own directive id rather than
the engine's uid. A `RunAccepted` event is optional rather than forced.

**Latches are a per-device fact with no general rule.** Section 4 is the
second engine whose stop signal is sticky. A control seam that writes one
and does not unlatch it breaks the next run, and which fields latch is
knowledge that lives in a device's documentation, not in a protocol.

## What this spike did not do

It did not run queueserver, so section 7 answers the identity question
for a bare RunEngine only. A queueserver deployment assigns an item uid
at submit time, which is a different and probably better answer, and it
needs Redis and a second sitting.

It used caproto's `FakeMotorIOC` rather than a real controller. The
record semantics are the ones under test and they are the real ones,
`.VAL` being a writable field chief among them, but a particular
controller may differ in how it behaves when `.VAL` changes mid-move.

It did not try to make the stack notice. What section 1 shows is that
nothing notices in the default configuration, not that no configuration
would. ophyd has settle and tolerance machinery that was not enabled
here, and a check comparing readback against the scan's intended
trajectory would catch section 2 and possibly section 3.

It touched one motor, one scan and one process. Nothing here says
anything about multi-device procedures, about Tango, about a data store
or about a transfer.

## Refreshing this

```sh
uv run --with caproto --with ophyd --with bluesky --with pyepics \
    python spikes/conductor/collide.py

uv run --with caproto --with ophyd --with bluesky --with pyepics \
    python spikes/conductor/orphan.py

uv run --with caproto --with ophyd --with pyepics \
    python spikes/conductor/shared_device.py
```

About ninety seconds together. Both overwrite their captures.

What reproduces exactly and what does not is worth knowing before reading
a diff. Section 2 reproduced to four decimal places across three runs,
including the 16 second duration, because once the rival's move takes
over the trajectory is determined. Sections 3 and 4 both stop the motor
wherever it happened to be when the write landed, so their third reading
was 1.6667 on some runs and 1.5556 on others. The finding in each case is
the shape rather than the number: setpoint agreeing with readback at a
point nobody asked for, and four identical readings in a two second
scan.

## When to delete this

When the device-claim question in "What this changes" is answered, which
is the only reason it exists. Keep `collisions.json` if a conductor is
ever written: it is what two writers on one device actually produce, and
it makes a fixture that needs neither EPICS nor a beamline.
