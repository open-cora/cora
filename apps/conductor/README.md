# Conductor

Walks a procedure across a beamline's seams, one step at a time, and
refuses a step whose hardware another walk is already holding.

**Drives a motor, over real Channel Access.** The pure core is here and
tested, and so are the two seams that touch a beamline, though not
equally.
`conductor.adapters.epics_control` moves and verifies single records,
checked against a caproto soft IOC rather than a double.
`conductor.adapters.bluesky_acquisition` runs a named plan and reads both
of a run's names back out of what the engine published, checked against a
double: no scan has been started from this package, only from
`spikes/conductor/`, which is where every behaviour that double imitates
was measured. See [What is missing](#what-is-missing).

**Reports each step as it ends.** A third seam, `Aroc`, has a
Protocol and no adapter. `conduct` announces the whole step list before
it runs anything, sends each outcome as its step ends, and closes the
walk on the way out, so a walk that dies leaves behind the steps that
finished rather than nothing at all. Where those reports go is a
deployment's choice, and what the arrangement does and does not promise
is `docs/reference/conducting.md`.

**The core names no outside system.** `claims`, `procedure`, `seams`,
`conduct` and `outcomes` import the standard library and each other, and
nothing else, so composing a procedure needs no beamline library
installed. Every adapter lives under `conductor/adapters/` and is named
once, at the entrypoint that picks it. That is enforced by
`tests/test_the_core_names_no_seam.py` rather than promised here.

Every design decision below came from `spikes/conductor/`, and the tests
name the finding each one answers.

## What it is, and what it is not

A client of AROC, not a part of it, the same way `apps/reporter` is. It
composes a routine nothing outside knows, drives it, and the runs it
causes reach AROC through the reporting surface that already exists.

- **Nothing here imports `aroc`, and nothing in `apps/api` imports this.**
  Its own project and its own lockfile make that the interpreter's rule
  rather than a convention.
- **It runs where the hardware is.** Channel Access is a local-network
  protocol and a motor is not driven from a datacenter.

It is not an engine. It does not own a scan's inner loop, it does not
know what a plan does, and it does not decide whether the science
worked. It asks an engine for a routine and it keeps two things straight
that no engine can: which step holds which device, and which run belongs
to which step.

## Why a claim is the centre of this package

Not a principle. A measurement, in `spikes/conductor/FINDINGS.md`.

A real scan was driven over a real motor while a second process wrote to
that motor. Four collisions, and all four runs ended `exit_status:
"success"`: one recorded four of its six points at a single position in
two seconds, one silently moved a point and left a record that agrees
with itself, and one left a field latched so the next run would break
too. The same write aimed at a motor the scan did not own changed
nothing at all.

So the hazard is two writers on one device, neither seam can see what the
other holds, and nothing downstream can catch it afterwards. A conductor
that did not prevent it would be a machine for producing confident wrong
data.

**The claim names records, not device objects.** Section 8 of those
findings, and `spikes/ophyd_adapter/` from the other side. Two ophyd
objects bound to one motor share no read keys at all, so two claims built
from them are disjoint by inspection and name the same hardware. Worse, a
blocking move through the second one returns before the motion starts.
The record name is what the IOC serves and the only vocabulary two
clients who have never met must agree on. `DESC` does not qualify: served
empty, writable by anyone, unique by nothing.

**And coverage is not `startswith`.** `2bmb:m1` and `2bmb:m10` are two
motors. A record covers itself and nothing else; a namespace is written
with its trailing separator and covers what is beneath it.

**What the ledger does not do is police one walk against itself.** A walk
is sequential and each claim is released as its step ends, so no two
steps of one procedure are ever held at once and none of them can
collide. The refusal bites between holders: two walks handed the same
ledger, or a walk started while something else has already taken a
motor. That is the arrangement, not a gap, and it is why `conduct` takes
a ledger rather than making one. It is also single-threaded: `Ledger`
checks and then writes without a lock, which is sound while one thread
walks at a time and is the first thing to change if parallel steps ever
arrive.

## The design in one picture

```
   the core: standard library and each other, nothing else
   ------------------------------------------------------
   procedure.py            claims.py              seams.py
     Move   -> claim         Scope                  Control
     Acquire   declares      Claim                    move, read
                             Ledger                 Acquisition
                               acquire                acquire
                               release              Aroc
                                                      report
                                                      step_ended
                                                      walk_ended
          \                     |                      /
           \                    |                     /
            +-----------> conduct.py <---------------+
                            one step at a time,
                            holding its claim
                                 |
                                 v
                            outcomes.py
                              Done Refused Broke Skipped
                                 |
                                 v
                            out through Aroc, one at a time,
                            because the tally is built too late to
                            survive anything

   adapters/: each one knows a single outside system
   -------------------------------------------------
   epics_control.py   implements Control over pyepics
                        refuses a held record
                        waits on the readback
                        waits for the motion to stop
                        says which of those it managed

   bluesky_acquisition.py
                      implements Acquisition over a RunEngine
                        carries the directive id into the start
                        reads the engine's run uid back out
                        refuses a plan that opened two runs
                        imports nothing: an engine is handed over

   The arrow between them points one way and only at the entrypoint.
   Nothing above imports anything below.
```

A `Move` derives its claim from the record it moves. An `Acquire` cannot:
which devices a plan touches is inside the plan, and a start document
describes one invocation rather than the routine, so there is nothing to
derive from. An acquisition step that declares nothing is refused where
it is built, because the alternative is a procedure whose most dangerous
step claims least.

The walk is sequential and stops at the first step that does not finish.
Steps not reached are reported as `Skipped` rather than omitted, so the
tally shows the whole procedure and where it stopped. Every outcome goes
out through `Reporting` as it is produced, skips included: whether a run
of them is worth a call each is a property of a particular way of
recording, and deciding it in the loop would put one deployment's cost
model in the path of all of them.

A recording failure is not caught. An adapter that means to carry on
while nothing can be told handles its own outage, which is what keeps
the degraded case a deployment's question rather than this loop's. It
also sits outside the `except` that produces `Broke`, because a move
that arrived and could not be reported did not break.

## Two things it deliberately will not claim

**That a step worked.** `Done` means the seam returned without raising.
Every corrupted scan in the findings came back `success`, so a word here
meaning "it did what it meant to" would be an overclaim of exactly the
kind `apps/api` refused when it chose `reported` over `witnessed`. What
the engine said travels verbatim and something further out decides.

**That dying stops anything.** A driver was SIGKILLed mid-move and the
motor travelled to its target with nothing alive that had asked for it,
and no stop document was ever emitted. SIGKILL offers no hook. So the
ledger is not durable, and anything that must stop on abandonment needs a
watchdog beside the hardware, which is neither this package nor AROC.
What a killed walk can leave behind is its record, which is a narrower
thing and the one `Aroc` exists for.

## The control adapter, and why it does more than a put

`conductor.adapters.epics_control` is the first seam with something behind it. A
put that waits would be the obvious implementation and it is not enough,
because two of the three corruptions in the findings are reachable
through one:

- A rival write to `.VAL` redirects the motor, and the completion that
  comes back belongs to the rival's move.
- `.SPMG` set to Stop holds the motor, and every later move returns at
  once having done nothing.

So it refuses a record whose hold field is not `Go`, it waits on `.RBV`
rather than on the put, it waits for `.DMOV` to say the motion finished,
and `Verified` says which of those it managed. A record serving no
readback is confirmed against itself, which proves the put landed and
nothing more, and says so rather than implying otherwise.

**Position alone was not enough, and a gate review caught it.** Waiting
only on `.RBV` let the `rival_move` case through: a motor redirected past
its target crosses the tolerance window on the way, so a poll looking
only at position can catch it in transit and call that arrival. Measured
against the soft IOC, a move to 3.0 with a rival redirecting to 9.0
mid-flight came back as arrived at three of four deadbands, every time
with `.DMOV` reading 0. The walk above would then have released the claim
and started the next step against a motor still travelling. Arrival is
two conditions now, and `StillMovingError` is the case where position
agreed and motion had not stopped.

The suite has a paired test that makes the point: the same move succeeds
undisturbed and raises `DidNotArriveError` when a rival redirects it
mid-flight, with the same settle on both, so the failure cannot be a
timeout dressed up as a finding.

**That test spent a while passing for the wrong reason**, which is the
other half of what the review found. It failed eight times out of eight
on its own and passed in a full run, because `motor_at_home` homed with
`epics.caput(..., wait=True)` and half a second, and a put returns while
the motor is still travelling. Every test inherited a motor still
drifting back from the one before it, and that residual motion was what
made the assertion hold. The fixture homes through the adapter now, which
is the same correction
`test_move_on_a_held_motor_leaves_it_where_it_was` had already made for
itself after asserting against 0.5556. Homing honestly is most of why the
suite now takes ninety seconds rather than fifty.

## Running it

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check src tests typings && uv run ruff format --check src tests typings
uv run pyright src tests
```

The suite starts a caproto soft IOC and talks to it over a real Channel
Access socket, so it takes about ninety seconds and needs no beamline.
Tests that need the IOC carry the `channel_access` marker, and each of
them is given both motors unlatched, at zero and at rest first.

## What is missing

| Piece | Waiting on |
| --- | --- |
| An acquisition adapter driven against a real engine | A sitting with one. `bluesky_acquisition` is written and checked against a double built from what `spikes/conductor/` measured, which is not the same as having run it. |
| A queueserver adapter | A decision. A bare RunEngine hands a caller nothing at submit time, so the uid that joins arrives only when the plan finishes; queueserver assigns an item uid up front, which would let a conducted run be named before it exists. That is a different and probably better answer, and it needs Redis and a second sitting. |
| A bound on how long an acquisition may take | An adapter to bound. `Control` has three clocks and `Acquisition` has none, so a scan that hangs hangs the walk. The right timeout is a property of the engine rather than of this Protocol, which is the argument for settling it with the first adapter rather than before it. |
| Any logging at all | A decision about where it goes. `Broke` keeps one line of text and no traceback, which is thin for something that will run unattended for hours, and `except Exception` files a typo in an adapter under the same word as a motor that would not move. |
| A control seam that is not EPICS | Something asking. Tango is the obvious second, and the Protocol has two verbs, so the cost is the adapter rather than the design. |
| An adapter behind `Aroc` | A client, and the identity to run as. The seam is here and `conduct` uses it; nothing yet turns a report into a request. `apps/reporter` has already settled the four questions any AROC client meets, and `docs/reference/client-contract.md` names where it keeps each answer. |
| Anything reaching AROC | A client, and the identity to run as. The runs this causes are reported through the surface `apps/reporter` already uses, and the join is the engine's own run uid, which `Acquired.engine_reference` carries out through `Done`. Resolving it is `GET /runs?external_ref_scheme=...`, and `docs/reference/client-contract.md` holds both halves of that agreement, including why the minted reference is not the join. |
| Configuration | A procedure is built in Python today. A file format is worth having once something outside a test writes one. |
| Parallel steps | Nothing has asked. The ledger is already the mechanism: two steps may run at once exactly when their claims do not overlap. |
| A Procedure aggregate in AROC | Deliberate. Three of four corrupted runs in the findings arrive as Completed, so an enactment record would say every step finished, which is true and useless. This package is what will say what such a record should hold. |
