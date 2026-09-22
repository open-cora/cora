# Conductor

Walks a procedure across a beamline's seams, and refuses any step that
wants hardware another step is holding.

**Drives a motor, over real Channel Access.** The pure core is here and
tested, and so is one of the two seams: `conductor.epics_control` moves
and verifies single records, checked against a caproto soft IOC rather
than a double. What is still a Protocol with nothing behind it is
acquisition, so no scan has been started from here. See
[What is missing](#what-is-missing).

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

## The design in one picture

```
   procedure.py            claims.py              seams.py
     Move   -> claim         Scope                  Control
     Acquire   declares      Claim                    move, read
                             Ledger                 Acquisition
                               acquire                acquire
                               release
          \                     |                      /
           \                    |                     /
            +-----------> conduct.py <---------------+
                            one step at a time,               |
                            holding its claim                 | implemented by
                                 |                            v
                                 v                      epics_control.py
                            outcomes.py                   refuses a held record
                              Done Refused                 waits on the readback
                              Broke Skipped                says which it checked
```

A `Move` derives its claim from the record it moves. An `Acquire` cannot:
which devices a plan touches is inside the plan, and a start document
describes one invocation rather than the routine, so there is nothing to
derive from. An acquisition step that declares nothing is refused where
it is built, because the alternative is a procedure whose most dangerous
step claims least.

The walk is sequential and stops at the first step that does not finish.
Steps not reached are reported as `Skipped` rather than omitted, so the
tally shows the whole procedure and where it stopped.

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

## The control adapter, and why it does more than a put

`conductor.epics_control` is the first seam with something behind it. A
put that waits would be the obvious implementation and it is not enough,
because two of the three corruptions in the findings are reachable
through one:

- A rival write to `.VAL` redirects the motor, and the completion that
  comes back belongs to the rival's move.
- `.SPMG` set to Stop holds the motor, and every later move returns at
  once having done nothing.

So it refuses a record whose hold field is not `Go`, it waits on `.RBV`
rather than on the put, and `Verified` says which field it checked
against. A record serving no readback is confirmed against itself, which
proves the put landed and nothing more, and says so rather than implying
otherwise.

The suite has a paired test that makes the point: the same move succeeds
undisturbed and raises `DidNotArriveError` when a rival redirects it
mid-flight, with the same settle on both, so the failure cannot be a
timeout dressed up as a finding. One test's own setup had to be rewritten
to use the adapter, because `epics.caput(..., wait=True)` returned while
the motor was still travelling and left the test asserting against 0.5556.

## Running it

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check src tests typings && uv run ruff format --check src tests typings
uv run pyright src tests
```

The suite starts a caproto soft IOC and talks to it over a real Channel
Access socket, so it takes about fifty seconds and needs no beamline.
Tests that need the IOC carry the `channel_access` marker.

## What is missing

| Piece | Waiting on |
| --- | --- |
| An acquisition adapter | A decision on queueserver. A bare RunEngine carries a reference it is given into the start document, which is what `Acquired.reference` is for; queueserver assigns its own item uid at submit time, which may be the better handle. Neither has been driven from here. |
| A control seam that is not EPICS | Something asking. Tango is the obvious second, and the Protocol has two verbs, so the cost is the adapter rather than the design. |
| Anything reaching AROC | A client, and the identity to run as. The runs this causes are reported through the surface `apps/reporter` already uses, and the join is the minted reference resolved through `GET /runs?external_ref_scheme=...`. That is the arrangement Counsel settled for proposals. |
| Configuration | A procedure is built in Python today. A file format is worth having once something outside a test writes one. |
| Parallel steps | Nothing has asked. The ledger is already the mechanism: two steps may run at once exactly when their claims do not overlap. |
| A Procedure aggregate in AROC | Deliberate. Three of four corrupted runs in the findings arrive as Completed, so an enactment record would say every step finished, which is true and useless. This package is what will say what such a record should hold. |
