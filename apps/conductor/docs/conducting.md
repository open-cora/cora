# Conducting

*What a conducted walk promises, and what survives when the thing conducting it does not.*

This project runs as a process at one beamline. It asks the keeper what has been dispatched there, claims one execution, walks it reporting each step as the step ends, and asks again. Nothing dispatches to it and it listens on nothing: every call goes out, over the same HTTP surface every other client of the keeper uses.

That is right for a library a person runs from a terminal and wrong for the direction this system is going. The keeper is to be an execution path rather than only a record of one: an actor puts a proposal forward, and what runs it is a conductor rather than the actor's own connection to an engine. The reason is the engineless beamline. A conductor drives hardware through `Control`, which needs no engine at all, so a procedure walks at a beamline that has never heard of an acquisition engine. Routing conducted work through an engine would make the capability depend on which software a facility adopted.

A walk therefore has to outlive the session that asked for it. This page says what that service promises and, more importantly, what it refuses to promise, because the interesting limits here are measured rather than argued.

## What the service promises, and what it cannot

```
   promised        the RECORD of a walk survives the walk
   not promised    the walk survives
   not promised    the hardware stops when the walk stops
```

The distinction is not pedantry. A spike killed a driver mid-move with SIGKILL and the motor travelled to its target with nothing alive that had asked for it, and no stop document was ever emitted. SIGKILL offers no hook, so no arrangement above the hardware can promise the third line. Anything that must stop on abandonment needs a watchdog beside the hardware, which is neither this system nor its conductor.

So "safe across its own restart" means that what the walk did is still known afterwards. It does not mean the walk is recoverable, and it does not mean the beamline is where the procedure left it.

## Two granularities

Coordination splits in two, and only the coarse half is durable.

| | held by | granularity | lifetime | durable |
| --- | --- | --- | --- | --- |
| lease | the keeper | the device set a procedure declares | one walk | yes |
| claim | the conductor's `Ledger` | one device, one step | one step | no |

A walk takes its lease once, at the start, over the union of the scopes its steps declare. A step takes its claim from the in-process ledger and releases it on the way out of the block, exactly as it does today.

The split is forced by where the parts run. A conductor runs at the beamline because Channel Access is a local-network protocol, and the keeper runs centrally. Putting a claim grant on the far side of that link would place a round trip inside every motor move, over a connection whose reachability is still an open question in `beamlines/EXPANSION.md`. One lease per walk pays that cost once.

It also matches what was measured. A spike compared a coarse whole-instrument lock beside a fine per-step claim and concluded a conductor plausibly wants both, because they are statements of different sizes: one says who owns the instrument for a while, the other says which device this step needs. Here the keeper holds the coarse one.

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

**This section used to describe two nested records and it now describes one.** A walk's steps and the engine runs they caused were a Walk aggregate and a Run aggregate, and the keeper held both. The Run aggregate has been retired: an acquisition step and a run turned out to be the same fact in two vocabularies once the keeper started composing the work, and most steps cause no engine run at all. See Execution.

So there is one record, and the engine's account of an acquisition hangs off the step rather than beside it:

```
   Execution         the procedure the keeper dispatched
     step            move, set, acquire
       outcome       what the conductor observed
       engine state  what the engine said, on an acquisition only
```

A move drives a motor and opens nothing, so its engine state stays empty for the life of the record. That asymmetry is why the collapse went step-ward rather than run-ward.

**A reserved table of driving verbs used to sit behind this**, pairing each reporting verb with the one a driving surface would use. It is gone, and the question was answered rather than dropped: the keeper dispatches a whole procedure, so the driving verb is `dispatch_execution`, it exists, and it is the only one. Execution records the removal.

**A step's record of what an engine did is a weaker statement than the step's own record.** A conductor reports an acquisition the moment the engine returns; whatever watches that engine relays the engine's view on its own schedule, as a different process. Nothing orders the two, so a step can be `Done` with no engine state at all, and the two can disagree once both arrive. They are two fields rather than one for exactly that reason.

The engine's name for the run travels on the step as `engine_reference`, which is what [Client contract](client-contract.md) says such a reference is: a correlation hint rather than a key anything is checked against. No amount of ordering the writes fixes the gap, because the two writes come from two clients that do not know about each other.

The record is a separate aggregate and it is called **Execution**. A walk is what the conductor does; an execution is what the keeper records of it, and the two words stay apart on purpose because the conductor keeps walking whether or not anything is recording.

## How the record reaches the keeper

Through a seam, beside the two that drive hardware. The Protocol is in `conductor.seams`, and `conductor.adapters.keeper_http` implements it over the same HTTP surface every other client uses.

**The seam is now `Keeper`, and it asks rather than announces.** It replaced `Recording`, whose first call took a caller-minted reference, a procedure name and a step list, all three of which the keeper writes at dispatch before anything is asked to drive them.

```
   take(beamline, wait)      what is dispatched here and unclaimed
   claim(execution_id)       this conductor is driving it, or 409
   report(id, index, outcome) how one step ended
   finish(execution_id)      nothing further is coming
```

`take` is a long poll rather than a poll: it is given how long it may block and returns the moment work appears. `claim` returning False is ordinary rather than a failure, because nothing reserves an assignment for whoever read it and two conductors seeing one execution is expected.

`conduct` does not take that seam. It takes `Reporting`, which is the two verbs a walk uses, already bound to the execution it is walking, so a walk cannot ask for work or claim any. `reports_to` is the binding.

**The loop is `conductor.intake`, and `python -m conductor` runs it.** It takes, claims, walks and repeats, for as long as it is left running, and it is given its seams rather than building any, so the one module that names an adapter is the entrypoint. Everything it catches gets one policy: say what happened, wait, ask again. There is deliberately no judgement about which failures are permanent, because a daemon that exited on one would hand a service manager a crash loop in place of a retry loop.

```
   Control        reading and writing one record at a time
   Acquisition    asking an engine to run a routine
   recording      telling the keeper what this walk is doing
```

The conductor's core names no outside system: `claims`, `procedure`, `seams`, `conduct` and `outcomes` import the standard library and each other, and a test in that package holds them to it. A direct dependency on the keeper would break that rule for the one client that most needs to stay honest about it.

A seam keeps the core pure and leaves the choice to a deployment, which is the same arrangement `Control` and `Acquisition` already use. It also gives the open question about degraded operation a shape rather than an answer: whether a conductor may walk while the keeper is unreachable becomes a question about which adapter a beamline installs, not a question about how the walk is built.

## Why the ledger does not move

`Ledger` argues its own non-durability, and the argument is right: a ledger that survived a restart would be claiming to know something it does not, because the hardware kept moving after the process died.

The lease does not contradict that, because it is not the same claim. A held claim says a live step is using this device now. A lease says a walk was given this device set and has not reported finishing with it. The first is false the instant the process dies. The second stays true, and is the fact a second conductor needs.

That is why the expiry rule above matters so much. A lease that expired into "free" would be a durable ledger by another name and would inherit the objection in full.

## What this does not promise

**That a step worked.** Unchanged from today. `Done` means the seam returned without raising, and every corrupted scan in a spike came back reporting success. A record that said otherwise would be the overclaim this tree refuses everywhere else.

**That a walk can be stopped while a step is running.** There is no interruption point inside a step. `EpicsControl` waits for arrival in a poll loop bounded by its settle time, and `BlueskyAcquisition` runs the engine in the calling thread. So an abort request lands between steps, and a step already running finishes or times out on its own terms. Interrupting one needs a worker and an engine-side abort, which is the same conclusion the bound on an acquisition step reached from the other direction.

**That the keeper knows about writers that do not go through it.** A lease arbitrates conducted work against other conducted work. A scientist at their own session on the same beamline is invisible to it, as they are to the in-process ledger today.

**That the record is complete when a conductor is killed between a step and its report.** The gap is one step wide and the step lands as unknown, which is the honest answer and not a recoverable one.

## What is not decided yet

**The fourth terminal.** `docs/bounded-contexts/execution.md` asks for a way to say an engine run ended without saying how, and notes that settling it matters more once something drives these executions. This is that direction, so the question is now in the way rather than ahead of it. One of the spikes found an engine that offers such a terminal natively, with a stated cause, and another found an engine whose completion string cannot distinguish a finished scan from a stopped one.

**A fifth outcome.** `Skipped` means the walk had already stopped before reaching this step and `Broke` means the seam raised. Neither means abandoned, and the restart rule above needs a word for it.

**An execution nobody is driving any more is invisible, and the answer is a view rather than a lease.** Settled in conversation on 2026-09-25 and not yet built.

A conductor that dies between its claim and its ending leaves an execution at `Claimed` or `Running` with no ending, and nothing reclaims it. `ExecutionEnded` already says its own absence is the load-bearing part; this is that absence with nobody watching for it.

The obvious fix is a lease: a claim expires unless it is renewed, and the work returns to `Dispatched` for somebody else. That is refused, for the reason the restart rule above gives. A conductor that died mid-procedure left the hardware wherever the last step put it, so handing that execution to a second conductor means starting step four on a beamline in a state nothing described. Refusing to resume is the existing rule and an expiring claim would quietly undo it.

What is wanted instead is the question asked out loud: which executions have been `Claimed` for longer than anything at this beamline plausibly takes, with no step reported since. That is a read over `status` and `updated_at`, both of which are already on `proj_execution_execution_summary`, so it costs a query and no new mechanism. It tells somebody to go and look, which is the only safe answer, rather than deciding on their behalf.

The threshold is the open part. A tomography scan and an alignment differ by orders of magnitude, so one number for all of them is either useless or wrong, and the honest first version reports the age rather than judging it.

**Whether a conductor may walk while the keeper is unreachable.** Named as a seam question above and not answered. The objection to answering it yes is that a walk recorded in two places is a walk with two versions of what happened.

**How a taken-up proposal becomes a procedure.** A proposal cites a plan and carries parameters; a procedure declares claims and bounds per step. Nothing turns one into the other, and the claim a proposed step needs has to come from somewhere.
