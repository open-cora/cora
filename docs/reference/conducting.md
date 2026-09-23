# Conducting

*What a conducted walk promises, and what survives when the thing conducting it does not.*

`apps/conductor` walks a procedure as a library, inside whatever process imported it. It reports each step as the step ends, through a seam whose Protocol is written and whose adapter is not, so where those reports go is still nowhere. Until one exists, a walk that dies takes its record with it.

That is right for a library a person runs from a terminal and wrong for the direction this system is going. AROC is to be an execution path rather than only a record of one: an actor puts a proposal forward, and what runs it is a conductor rather than the actor's own connection to an engine. The reason is the engineless beamline. A conductor drives hardware through `Control`, which needs no engine at all, so a procedure walks at a beamline that has never heard of an acquisition engine. Routing conducted work through an engine would make the capability depend on which software a facility adopted.

A walk therefore has to outlive the session that asked for it. This page says what that service promises and, more importantly, what it refuses to promise, because the interesting limits here are measured rather than argued.

## What the service promises, and what it cannot

```
   promised        the RECORD of a walk survives the walk
   not promised    the walk survives
   not promised    the hardware stops when the walk stops
```

The distinction is not pedantry. `spikes/conductor/FINDINGS.md` killed a driver mid-move with SIGKILL and the motor travelled to its target with nothing alive that had asked for it, and no stop document was ever emitted. SIGKILL offers no hook, so no arrangement above the hardware can promise the third line. Anything that must stop on abandonment needs a watchdog beside the hardware, which is neither this system nor its conductor.

So "safe across its own restart" means that what the walk did is still known afterwards. It does not mean the walk is recoverable, and it does not mean the beamline is where the procedure left it.

## Two granularities

Coordination splits in two, and only the coarse half is durable.

| | held by | granularity | lifetime | durable |
| --- | --- | --- | --- | --- |
| lease | AROC | the device set a procedure declares | one walk | yes |
| claim | the conductor's `Ledger` | one device, one step | one step | no |

A walk takes its lease once, at the start, over the union of the scopes its steps declare. A step takes its claim from the in-process ledger and releases it on the way out of the block, exactly as it does today.

The split is forced by where the parts run. A conductor runs at the beamline because Channel Access is a local-network protocol, and AROC runs centrally. Putting a claim grant on the far side of that link would place a round trip inside every motor move, over a connection whose reachability is still an open question in `beamlines/EXPANSION.md`. One lease per walk pays that cost once.

It also matches what the spikes found. `spikes/queueserver_adapter/FINDINGS.md` measured a coarse whole-instrument lock beside a fine per-step claim and concluded a conductor plausibly wants both, because they are statements of different sizes: one says who owns the instrument for a while, the other says which device this step needs. Here AROC holds the coarse one.

**An expired lease does not mean the devices are free.** It means they were last touched by a walk that stopped reporting, which is a different fact and a weaker one. Releasing them to the next caller would assert that the previous walk finished touching them, which is the claim the SIGKILL measurement refutes.

## What a restart does

A walk found in flight is closed. Nothing is resumed and nothing is retried.

```
   before the gap   [ Done ][ Done ][ in flight ][ not reached ][ not reached ]
   after restart    [ Done ][ Done ][  unknown  ][   Skipped   ][   Skipped   ]
```

Steps confirmed before the gap stand, because each was reported as it happened. The step in flight is recorded as ended with its outcome unknown: the conductor cannot say whether the motor arrived, and the engine may or may not have opened a run. The steps never reached are `Skipped`, which is what a walk already reports for steps after it stops.

Refusing to resume is a choice and the cheaper of two. The alternative is to read the hardware back, compare it against what the procedure expected, and continue if they agree. That is a stronger guarantee and it needs a reconcile operation per adapter that nothing offers today. It is worth building later; it is not what this describes.

The reason to prefer closing over resuming is not only cost. A walk stops at its first failure because the next step was written on the assumption that the one before it worked, and a gap in the record is exactly that kind of failure. Resuming across one would be guessing about a beamline nobody observed.

## Where a conducted walk is recorded

A walk is not a run. One walk holds many steps, and an acquisition step causes a run while a move or a set does not. So there are two records and they nest:

```
   walk        the procedure this system was asked to drive
     step      move, set, acquire
       run     what an engine did, when the step was an acquisition
```

The runs a conducted walk causes take the driving genesis that `docs/bounded-contexts/execution.md` reserved. That page fixed the vocabulary in advance: a reported run and a conducted one are different commands producing differently named events, with no field naming the axis, so which event opened a stream is what says who drove the act. It also fixed which verbs move to the driving side and which never do, since even a driving AROC tells an engine to start and is then told how it went.

Nothing issues those reserved names yet. This page does not add them; it says which surface a conducted walk will use when they land, so that nobody invents a second scheme in the meantime.

The walk's own record is a separate aggregate and it does not have a name here. Naming it is left open below.

## How the record reaches AROC

Through a seam, beside the two that drive hardware. The Protocol is in `apps/conductor` and `conduct` calls it; nothing implements it yet.

```
   Control        reading and writing one record at a time
   Acquisition    asking an engine to run a routine
   recording      telling AROC what this walk is doing
```

The conductor's core names no outside system: `claims`, `procedure`, `seams`, `conduct` and `outcomes` import the standard library and each other, and a test in that package holds them to it. A direct dependency on AROC would break that rule for the one client that most needs to stay honest about it.

A seam keeps the core pure and leaves the choice to a deployment, which is the same arrangement `Control` and `Acquisition` already use. It also gives the open question about degraded operation a shape rather than an answer: whether a conductor may walk while AROC is unreachable becomes a question about which adapter a beamline installs, not a question about how the walk is built.

## Why the ledger does not move

`Ledger` argues its own non-durability, and the argument is right: a ledger that survived a restart would be claiming to know something it does not, because the hardware kept moving after the process died.

The lease does not contradict that, because it is not the same claim. A held claim says a live step is using this device now. A lease says a walk was given this device set and has not reported finishing with it. The first is false the instant the process dies. The second stays true, and is the fact a second conductor needs.

That is why the expiry rule above matters so much. A lease that expired into "free" would be a durable ledger by another name and would inherit the objection in full.

## What this does not promise

**That a step worked.** Unchanged from today. `Done` means the seam returned without raising, and every corrupted scan in `spikes/conductor/FINDINGS.md` came back reporting success. A record that said otherwise would be the overclaim this tree refuses everywhere else.

**That a walk can be stopped while a step is running.** There is no interruption point inside a step. `EpicsControl` waits for arrival in a poll loop bounded by its settle time, and `BlueskyAcquisition` runs the engine in the calling thread. So an abort request lands between steps, and a step already running finishes or times out on its own terms. Interrupting one needs a worker and an engine-side abort, which is the same conclusion the bound on an acquisition step reached from the other direction.

**That AROC knows about writers that do not go through it.** A lease arbitrates conducted work against other conducted work. A scientist at their own session on the same beamline is invisible to it, as they are to the in-process ledger today.

**That the record is complete when a conductor is killed between a step and its report.** The gap is one step wide and the step lands as unknown, which is the honest answer and not a recoverable one.

## What is not decided yet

**The walk aggregate's name.** `Walk` is taken by the conductor's own return value and `Procedure` is the thing an author writes, so neither transfers. The test to apply is the one that picked Proposal over Decision: a record may not be named after something this system did not witness.

**The fourth terminal.** `docs/bounded-contexts/execution.md` asks for a way to say a run ended without saying how, and notes that settling it matters more once a second direction is built on the Run aggregate. This is that direction, so the question is now in the way rather than ahead of it. One of the spikes found an engine that offers such a terminal natively, with a stated cause, and another found an engine whose completion string cannot distinguish a finished scan from a stopped one.

**A fifth outcome.** `Skipped` means the walk had already stopped before reaching this step and `Broke` means the seam raised. Neither means abandoned, and the restart rule above needs a word for it.

**Whether a conductor may walk while AROC is unreachable.** Named as a seam question above and not answered. The objection to answering it yes is that a walk recorded in two places is a walk with two versions of what happened.

**How a taken-up proposal becomes a procedure.** A proposal cites a plan and carries parameters; a procedure declares claims and bounds per step. Nothing turns one into the other, and the claim a proposed step needs has to come from somewhere.
