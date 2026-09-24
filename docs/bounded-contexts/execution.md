# Execution

Execution is the bounded context that answers two questions: what can this system be asked to run, and what happened when it ran.

It holds four aggregates, in two pairs. A Plan is a runnable routine written down and a Run is one carrying-out of one, as this system came to know about it. A Procedure is the same idea one scale up, and an Execution is one traversal of one. Twenty-two operations across the four.

The difference between the pairs is who composed the routine. A plan names something an engine already has, so this system holds a reference to a thing it did not write. A procedure is authored here, out of moves and acquisitions, and nothing anywhere holds that sequence until the record says so.

The routine itself lives outside, in whatever **engine** the deployment runs. This context holds a record of what that engine can be asked for and what it did, never the running of it.

## What a Plan is

A plan is something this system can be asked to run, written down.

```
   Plan
     id                 a UUID minted at definition, never reused
     name               what the engine calls the routine
     parameters_schema  the shape a run of it must supply
```

Three fields. The name is not decoration: it is how the engine identifies what to run, so a plan without one names nothing and there is no act to record.

Two plans may share a name and nothing stops that. That follows from what the name is for rather than being a rule of its own. This system identifies a plan by its id everywhere it matters: a run cites an id, and `GET /plans/{plan_id}` reads one back. The name is the handle the engine uses, carried so this system can eventually say which routine to run, and a handle does not have to be unique to do that job.

One routine constrained two ways is two plans, and which one a run cites is what says how it was constrained. Be aware of how little of that difference the record can currently hold: the schema subset has no `items` keyword, so two plans that differ only in which devices they allow are the same document twice, distinguishable by id and nothing else.

## Why the schema is required

A plan carries a JSON Schema, in the constrained subset described in [Conventions](../reference/conventions.md#schema-validated-values), and it is required rather than optional.

The shared carrier-side validator accepts an absent schema and refuses the values that would have gone with it. A plan closes that case earlier, at definition. An operator with nothing to constrain declares a schema that constrains nothing and says so in the record; the alternative is a plan that can never refuse a parameter, with nothing saying whether that was meant.

So of the four cells in that posture table, the absent-schema row is unreachable from here. It stays in the shared helper because the helper is shared and the next declarer may want it.

## What a Procedure is

A procedure is a routine this system composed: an ordered list of steps, each naming what it touches.

```
   Procedure
     id      a UUID minted at definition, never reused
     name    what this system calls the routine
     steps   moves and acquisitions, in order
```

Two kinds of step, and only one of them declares what it touches.

```
   Move      record, to           what it touches is the record it names
   Acquire   plan_id, parameters, scopes
```

A move sends one record to one value, so deriving what it touches is exact and a declared field would be a second chance to say the same thing differently. An acquisition hands a routine to an engine, and nothing here can see inside that routine to work out which devices it will drive. So an acquisition declares its scopes and a move does not have the option, which is not an inconsistency: one is derivable and the other is not.

An acquisition must declare at least one scope. A step that declared none would be one this system believes touches no hardware, and that belief is what lets two of them run at once over one motor.

### What a scope is, and what this system does with it

Nothing. A scope is stored as the string it arrived as, and is not parsed into a namespace and a flag. Whatever drives the procedure owns that grammar, the overlap arithmetic runs in that process against its own ledger, and a second implementation here would be two things to keep in step for no reader's benefit. What is checked is that a scope is a non-empty string within a bound, which is what makes it storable.

### Where the parameters are checked

An acquisition's parameters are validated against the schema its plan declares, and the check runs at definition rather than when the procedure is walked. That is earlier and cheaper: a procedure with a malformed acquisition is refused before anything is dispatched, instead of failing partway through a traversal that has already moved motors.

Two gaps in that check are worth stating rather than discovering. An acquisition supplying no parameters at all is accepted whatever its plan requires, because the shared validator defers `required` to the point the values are finally acted on, which is the engine. And a plan retired or redefined after the fact does not invalidate a procedure citing it: the parameters were checked against the schema as it stood, and the record is a record of what was composed.

## What a Run is

A run is one execution of a plan, as this system came to know about it.

```
   Run
     id            a UUID minted when the record is written
     plan_id       the plan that was run
     parameters    the values it was given
     external_ref  what the engine that ran it calls it
     status        Running, Paused, Completed, Aborted or Failed
```

`external_ref` is required. A run this system cannot point back at is a claim that something happened somewhere, with no way to check it or to find the data it produced. Refusing it costs a caller one field and buys every later reader the ability to follow the record to its source.

The parameters are checked against the plan's schema when the record is written, and not again. Re-reading the plan later may find a different schema, which does not make the record wrong: it makes it a record of what was run.

## The twenty-two operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Define a plan | `POST /plans` | `define_plan` | `201` with the new id |
| Read one back | `GET /plans/{plan_id}` | `get_plan` | `200` with the plan |
| Find plans | `GET /plans` | `list_plans` | `200` with a page of plans |
| Define a procedure | `POST /procedures` | `define_procedure` | `201` with the new id |
| Read one back | `GET /procedures/{procedure_id}` | `get_procedure` | `200` with the procedure and its steps |
| Find procedures | `GET /procedures` | `list_procedures` | `200` with a page of procedures |
| Report a run | `POST /runs` | `report_run` | `201` with the new id |
| Read one back | `GET /runs/{run_id}` | `get_run` | `200` with the run |
| Find runs | `GET /runs` | `list_runs` | `200` with a page of runs |
| It stopped where it was | `POST /runs/{run_id}/pause` | `pause_run` | `204` |
| It carried on | `POST /runs/{run_id}/resume` | `resume_run` | `204` |
| It reached its end | `POST /runs/{run_id}/complete` | `complete_run` | `204` |
| Something stopped it | `POST /runs/{run_id}/abort` | `abort_run` | `204` |
| It broke | `POST /runs/{run_id}/fail` | `fail_run` | `204` |
| Dispatch an execution | `POST /executions` | `dispatch_execution` | `201` with the new id |
| Something took it up | `POST /executions/{execution_id}/claim` | `claim_execution` | `204` |
| One of its steps ended | `POST /executions/{execution_id}/steps` | `report_step` | `204` |
| An engine moved a step's run | `POST /executions/{execution_id}/steps/{step_id}/run` | `report_step_run` | `204` |
| Nothing more is coming | `POST /executions/{execution_id}/end` | `end_execution` | `204` |
| Read one back | `GET /executions/{execution_id}` | `get_execution` | `200` with the execution and its steps |
| Find executions | `GET /executions` | `list_executions` | `200` with a page of executions |

All twenty-two are published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `apps/api/src/aroc/execution/routes.py`.

The six run operations that write take an optional `occurred_at`, and so do three of the four execution ones. The plan and procedure operations do not, and neither does dispatching an execution: a dispatch happens here, at the moment the record is written, so there is no earlier instant for a caller to report. That split is R8's, and it is explained under [When a run's transition happened](#when-a-runs-transition-happened) below.

`POST /runs` creates a record of something that already happened, not the happening. The resource being created is the record. A slice that actually starts a run gets its own path rather than a flag on this one, because the two differ in what the caller is asking for and not merely in a field.

Both schemas and parameters come back exactly as they were stored, not re-rendered. A caller generating a form, validating a request locally, or comparing what an engine was given against what it asked for has to be working from the record rather than from a rendering of it.

## What the streams hold

There is no plans table and no runs table. Current state is recomputed by replaying a stream on every read.

There are two derived tables, one per aggregate, and neither holds state the fold does not. See [Finding one without its id](#finding-one-without-its-id).

```
   PlanDefined        plan_id, plan_name, parameters_schema, occurred_at

   ProcedureDefined   procedure_id, procedure_name, steps, occurred_at

   RunReported   run_id, plan_id, parameters,
                 external_ref_scheme, external_ref_value, occurred_at
   RunPaused     run_id, occurred_at
   RunResumed    run_id, occurred_at
   RunCompleted  run_id, occurred_at
   RunAborted    run_id, occurred_at
   RunFailed     run_id, occurred_at
```

One event on a plan and one on a procedure, because nothing changes either yet. Retiring one arrives as a new class when the command that does lands, never as a field edited onto the genesis.

A procedure's whole step list rides its genesis, as a list of objects rather than flat fields, which makes it the only payload here holding a nested structure. Each step carries a `kind` discriminating a move from an acquisition. That key is on the wire and not on either class in the model, because there the class IS the kind and a field saying so again is a second thing to get wrong.

Every event after the genesis carries the same two fields. What is running is already on the stream, so a later event adds when, and which thing happened, and nothing else.

Neither `RunPaused` nor `RunResumed` says why, or where in the routine it happened. A pause raised by a signal, by an operator, and by the routine asking for one itself all arrive as the same fact, because stopped versus not is the distinction this system can act on and the rest is the engine's to keep.

The plan's name rides the payload as `plan_name` rather than `name`. The personal-data check reads field names and cannot tell a routine's name from a person's, and an unqualified `name` on an append-only row is the shape that rule exists to stop. The state keeps the bare `name`, where the aggregate it hangs off already supplies the qualifier.

The run's external reference travels as two flat strings and is rebuilt into a pair by the fold, because events carry primitives and that pair is a value object.

## The state machine

```
              report_run
                  │
                  ▼
            ┌─────────┐    pause_run     ┌──────────┐
            │ Running │ ───────────────► │  Paused  │
            │         │ ◄─────────────── │          │
            └────┬────┘    resume_run    └─────┬────┘
                 │                             │
                 └──────────────┬──────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                    │
      complete_run          abort_run             fail_run
           │                    │                    │
           ▼                    ▼                    ▼
    ┌───────────┐        ┌───────────┐        ┌───────────┐
    │ Completed │        │  Aborted  │        │  Failed   │
    └───────────┘        └───────────┘        └───────────┘

   any transition from any terminal             refused, 409
   pause_run on Paused, resume_run on Running   refused, 409
```

Two live statuses and three terminal ones. Three terminals rather than one with a reason beside it, because the engines this system is built to hear from report exactly these three, and a reader should not have to parse a string to recover a distinction the source already drew. They split by who or what ended the run: itself, someone else, or a fault.

All three endings are reachable from Paused as well as from Running, which is the edge most easily got wrong. A paused engine is exactly the one an operator aborts, and an engine that can pause offers ways to stop from paused for that reason. In the code this is one property: `has_ended` asks whether the status is terminal rather than whether it is not Running, and those two readings agree on every status except Paused.

Paused is the only status a run can leave, and the resume is the only edge pointing back. So the status is not monotonic while the stream still only grows, and a reader cannot infer how many events a run holds from where it ended up. A run that paused twice and carried on twice reads as Running with five rows behind it. The status is a reading of the history, not a tally of it, and a reader who wants the pauses reads the events.

`status` is not stored. The fold derives it from which events the stream carries, so it cannot disagree with the history behind it, and there is no payload field for a writer to get wrong.

Running says only that no ending has been reported and no pause stands over it. A run whose engine died with nobody to say so reads as Running here forever. That is an honest report of what this system has been told rather than a claim about the world, and closing it needs something watching rather than another value. Paused is the same kind of claim: the engine said it stopped, and nothing here has heard otherwise since.

No transient states. There is no Completing or Aborting, because there is no moment here where a command has arrived and its event has not. Transients belong to a system that waits, and this one does not yet.

Paused is not one of them. A transient is a state the system passes through on its own; a paused run sits there until something reports that it moved, and it may sit there for a week.

An ending is refused from every terminal, including a different one. The case worth naming is failing a run that already completed: an engine that reported success and then crashed on the way out looks exactly like that, and this system cannot tell which report was right. Keeping the first and returning a conflict makes the disagreement visible, where accepting the second would quietly overwrite a claim somebody already made.

Nothing carries a reason. A free-text reason is the field most likely to end up holding something about a person, in the one table that cannot be edited, and an engine's failure message is exactly that kind of text. `ActorDeactivated` carries none for the same reason.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidPlanNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidPlanParametersSchemaError` | 400 | Not a Draft 2020-12 document, or outside the stored subset. |
| `InvalidRunParametersError` | 400 | The values do not satisfy the plan's schema. |
| `InvalidProcedureNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidProcedureStepsError` | 400 | No steps, too many, a move naming no record or sent to a value JSON cannot carry, or an acquisition declaring no devices. |
| `InvalidProcedureParametersError` | 400 | An acquisition's parameters do not satisfy the plan it cites. Names which step. |
| `InvalidIdentifierError` | 400 | An external reference had an empty or over-long half. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `PlanNotFoundError` | 404 | The id names no plan, whether the caller asked to read one or named one while reporting a run. |
| `RunNotFoundError` | 404 | The id names no run. |
| `ProcedureNotFoundError` | 404 | The id names no procedure. |
| `PlanAlreadyExistsError` | 409 | Definition was aimed at an id that already has a history. |
| `RunAlreadyExistsError` | 409 | The same, for a run. |
| `ProcedureAlreadyExistsError` | 409 | The same, for a procedure. |
| `RunCannotBeCompletedError` | 409 | The run had already ended. |
| `RunCannotBeAbortedError` | 409 | The same, for an abort. |
| `RunCannotBeFailedError` | 409 | The same, for a failure. |
| `RunCannotBePausedError` | 409 | The run is not running: it had ended, or it was already paused. |
| `RunCannotBeResumedError` | 409 | The run is not paused: it had ended, or it was running all along. |
| `ConcurrencyError` | 409 | The run changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

The execution refusals are a second table rather than more rows in that one, because they were missing from it entirely and adding them in place would bury the distinction between an aggregate this system is told about and one it drives.

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidWalkProcedureNameError` | 400 | The procedure's name falls outside what an execution stores. |
| `InvalidWalkStepsError` | 400 | The rendered step list is empty, too long, or holds a blank step. |
| `InvalidStepReportError` | 400 | A step report carried a detail belonging to a different outcome, or a break named no cause. |
| `InvalidStepRunReportError` | 400 | The engine report does not follow the engine state already recorded. Carries both. |
| `WalkNotFoundError` | 404 | The id names no execution. |
| `WalkStepOutOfRangeError` | 404 | The index is past the end of the list the genesis fixed. |
| `WalkStepNotFoundError` | 404 | The same mistake made by id rather than by index. |
| `ProcedureNotFoundError` | 404 | A dispatch cited a procedure that does not exist. |
| `WalkAlreadyExistsError` | 409 | Dispatch was aimed at an id that already has a history. |
| `WalkCannotBeClaimedError` | 409 | The execution is not waiting to be taken up: something already claimed it, or it ended. Carries the status. |
| `WalkAlreadyEndedError` | 409 | A close arrived for an execution that had already closed. |
| `WalkStepAlreadyReportedError` | 409 | That step already has an outcome, and a step ends exactly once. |

`InvalidIdentifierError` is the odd one. It belongs to a shared value object rather than to an aggregate, so it does not follow the naming shape the other three do and is not defined in a state module. Nothing else registers a status for it, and unregistered it would be a 500.

The five transition refusals stay separate classes rather than collapsing into one keyed on a string. The verb in the class name is the diagnostic, the HTTP mapping keys off the class rather than a field, and the call site already knows which verb it called. Each carries the status the run is actually in, because being told a run already ended is much less useful than being told it ended by being aborted.

The pair refuses from a live status as well as from a terminal, which the three endings never do. Pausing a paused run and resuming a running one are both moves on a run that has not ended, and both are rejected: the first is a redelivery, and the second usually means two reporters disagree about what the engine did. The status on the refusal is what lets a caller tell those apart.

A plan that is not there and a plan that refuses the values are deliberately different statuses. One means fix the id, the other means fix the values, and a caller needs to tell them apart.

Names and references are checked twice on the HTTP path, and the two checks answer to different callers. One the request model can refuse never reaches a command and gets FastAPI's own 422; one it cannot, such as a string of spaces, is refused by the value object inside the decision function and gets 400. Neither covers the other's callers, because the MCP surface has no request model.

Reading is gated like writing. A plan says what this system can be asked to run and what a request has to look like, and a run record says what was actually run and with what. Both are things a deployment should get to decide who may see.

## When a run's transition happened

Every run command accepts an optional `occurred_at`, and a caller who omits it gets the moment their report arrived.

This matters most where it is easiest to overlook. For an adapter reporting live, the gap between when a run ended and when this system heard is milliseconds. For a reporter that was down for an hour it is an hour. For a backfill out of an engine's own archive it is years, and without this field every one of those runs would be recorded as having happened on the afternoon somebody ran the import.

An engine that records a run stamps its own records with when it happened, so on the reporting side the information was always there. Until now there was no way to send it.

`define_plan` does not take one, and the asymmetry is the point. A plan is authored here: the moment this system writes it is the moment it exists. A run happened somewhere else. That is R8 in [Naming](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one), and Execution is where it first shows up in code rather than in prose.

A supplied timestamp must carry an offset and is stored as UTC. It is not checked against anything else: not against the clock, not against the run's own genesis. A run may therefore claim to have completed before it started, or in the future.

That is not laxness, it is the same posture the rest of this context takes. An engine's `exit_status` is not second-guessed either. What is promised is that the record says plainly what was claimed, and separately says when it was written down, and the second of those is written by the database rather than by this application, so no caller can touch it. See the Time section in [Conventions](../reference/conventions.md#time) for the full reasoning.

A list row carries both timestamps and a single read carries neither, which is a decision on each side rather than an oversight on one. A list is read to find something, and when a run happened is how a person recognises the one they meant. A single read already names the run, so the question is answered before the timestamps could help.

## Finding one without its id

Two reads in this context name what they want. `GET /runs/{run_id}` and `GET /plans/{plan_id}` replay one stream each and answer from it, which costs one query and stays correct forever because the stream is the record.

Two questions cannot be answered that way, one per aggregate. An adapter draining an engine's output holds the engine's own id for a run, and the name that engine calls a routine, and neither of those is a stream id. Answering either would mean replaying every stream of its kind to see which ones match. A fold needs to know which stream to fold, and that is exactly what is being asked.

So there is a second read path:

```
   POST /runs                       GET /runs/{run_id}
   POST /plans                      GET /plans/{plan_id}
     |                                fold a stream each. Unchanged.
     | event
     v
   events  (the record)             GET /runs?external_ref_scheme=...
     |                              GET /plans?name=...
     | one worker, two bookmarks      read the tables below
     v
   proj_execution_run_summary
   proj_execution_plan_summary
```

Three things about it are worth knowing before reading a row.

**It lags.** `POST /runs` returns before the row exists. Normally tens of milliseconds, never zero. A caller that writes and immediately lists may not see what it just wrote.

**It can be thrown away.** Every column is derived from the event log, so dropping the table and resetting its bookmark to zero rebuilds it exactly. The log is the record; this is a convenience over it. That is why the table takes full `UPDATE` and `DELETE` while `events` does not.

**It is not a second way to write.** Nothing but the worker writes a row. A handler that wrote one directly would be inventing a fact the log does not hold.

There is a port per aggregate, `RunSummaryLookup` and `PlanSummaryLookup`, each declared with the aggregate it summarises, and two implementations of each. A deployment reads the table. An environment with no database folds every stream of that kind instead, which is the expensive thing the table exists to avoid and is free when the whole store is a dictionary. A shared contract suite per port runs against both of its sides, because the two sides share no code and the claim that they answer alike is otherwise just prose.

**A plan name is where the two questions differ.** A run's external reference is meant to be unique and merely is not enforced to be. A plan's name is not an identity at all: it is the engine's handle, and this system holds plans for every engine it hears from. So `GET /plans?name=count` returns however many there are, and it is a way to see them rather than a way to choose between them.

Choosing is the caller's, and a caller that has to choose holds a mapping rather than applies a rule. Something reporting runs from one engine knows which installation it serves and which plan each name means there; this system knows neither, and nothing on the two records would tell it apart if it tried. An operator who wants one answer pins a plan id. A lookup returning one of two would be making that choice on every call, silently, on the strength of an ordering nobody asked about.

## What an Execution is

An execution is one traversal of a procedure: the record this system opens when it dispatches one, and how far the thing driving it got.

```
   Execution
     id              a UUID minted when the record is written
     procedure_id    the routine that was dispatched
     procedure_name  its name, copied at dispatch
     steps           each with its own id: what it was asked to
                     perform, and how each ended
     status          Dispatched, Claimed, Running or Ended
```

Most steps cause no run at all, which is why an execution cannot be recorded as a run without losing every step that was not an acquisition.

Each step carries an id of its own, minted at dispatch and written onto the genesis. It is on the payload rather than made during the fold because a fold has to produce the same steps on every replay, and a record other aggregates point at cannot move between them.

A step has an id at all so that something outside can name one. A dataset is produced by one acquisition, not by a whole traversal, so `(execution_id, index)` would be a pointer into the interior of another aggregate rather than a handle: it cannot be fetched, and checking it exists means folding the whole execution and bounds-checking an integer. Nothing cites a step id yet; Custody and Counsel are where it will be used.

An execution cites its procedure and also copies its name and steps. The copy is not redundancy. The fold is pure and cannot load another stream, so the length of the step list has to ride the genesis for the outcomes to have anywhere to land, and once the count is there the descriptions cost one string each and save every reader a second read. It also keeps the record true if a procedure is ever made editable: this says what was dispatched, not what the definition says today.

### Why an execution has a status when a run's aggregate says there are none

The Run aggregate states plainly that this tree has no transient states, because there is no moment where a command has arrived and its event has not. That holds for a record of something somebody else did. It stops holding the moment this system dispatches.

Dispatching means waiting. An execution exists from the instant it is handed out, and nothing is driving it until something says so.

```
   dispatch_execution
        │
        ▼
   ┌────────────┐  claim_execution   ┌─────────┐  report_step  ┌─────────┐
   │ Dispatched │ ────────────► │ Claimed │ ────────────► │ Running │
   └─────┬──────┘               └────┬────┘               └────┬────┘
         │                           │                         │
         │ report_step               │                         │
         └───────────────────────────┴────────────┬────────────┘
                                                  │
                                              end_execution
                                                  │
                                                  ▼
                                            ┌──────────┐
                                            │  Ended   │
                                            └──────────┘

   claim_execution from anything but Dispatched    refused, 409
```

`Dispatched` is the first genuine transient in this tree, and it is one on purpose. A row sitting there with an old timestamp says nothing ever took the work up, which is a different failure from a driver that died partway: that one reads as `Running` with steps unreported. Nothing here can tell either from something merely slow, which is the limit [Conducting](../reference/conducting.md) names rather than papers over.

Claiming is refused from every status but `Dispatched`, which makes it the only command on this stream that refuses from a live status as well as the terminal one. A second claim is two drivers each believing they own one traversal. Nothing here can stop the second from moving a motor; what it can do is refuse to record that the execution was taken up twice, so the disagreement ends up in the log rather than only at the beamline.

Claiming is not a gate on reporting. A driver that reports a step without claiming first moves the execution straight from `Dispatched` to `Running`, and that is allowed: a claim says who has the work, and refusing the report would lose a fact this system was told in order to enforce an ordering the log does not have.

### No reference of its own

An earlier shape had the driver mint a name for the execution before its first step, because at that moment there was no handle to refer to. Under a dispatch there is: this system creates the record first, so the execution's id is the handle, and it is the id a driver carries into whatever it asks an engine to run.

Each step ends exactly once, in one of four ways:

```
   Done      the seam returned, which is not the same as the step working
   Refused   a claim conflict stopped it before it touched anything
   Broken    the seam raised
   Skipped   the execution had already stopped before reaching it
```

### Two observers of one step, kept apart

An acquisition step gets talked about twice, by two clients that do not know about each other.

```
   outcome        what the driver saw     Done, Refused, Broken, Skipped
   engine_state   what the engine said    Running, Paused, Completed, Aborted, Failed
```

They are two fields because they can disagree, and the disagreement is the point. `spikes/conductor/FINDINGS.md` drove four collisions into a real scan and every one of them ended `exit_status: "success"`, so neither observer is reliable and collapsing the two would make this system pick a winner between claims it cannot check. A step whose call returned while its engine reported a failure reads as `Done` and `Failed`, which is the honest record.

A move carries no engine state at all, because a move opens no run for anything to watch.

The five engine values are deliberately the five a run has. It is the same engine reporting the same lifecycle one scale down, and a reader who has learned one should not have to learn a second vocabulary for it. The transitions are the same too: all three endings are reachable from `Paused` as well as from `Running`, a resume is the only edge pointing backwards, and nothing follows an ending.

Neither account waits for the other. A driver may report its call returning before or after the engine reports the run ending, so requiring an order would refuse whichever arrived first. An engine's account is accepted even after an execution has been closed, because a driver that gave up does not stop the hardware from having done something, and that account is the only record of what it did.

`Done` is the word most likely to be read as more than it is. Every corrupted scan in `spikes/conductor/FINDINGS.md` came back reporting success, so the outcome says the call returned and nothing about whether the science worked. `Refused` is the only unambiguously good news in the set.

An outcome carries at most one detail, and two of the four carry none. A done step may name the run it opened and a broken step names the class that was raised. A refused step names nothing, and a skipped step never could.

That a refusal says nothing about the conflict is a boundary rather than a gap. Which step was holding the device, and which scopes collided, are facts about a ledger that lives in the driver's own process and is not durable by its own argument. Nothing here can act on either, and an append-only table is the wrong home for another process's working notes. A driver that wants to explain a refusal to a person has the ledger in front of it.

There is no value meaning abandoned. An execution whose driver died reads as `Running` with steps unreported and stays that way, because saying more needs something watching rather than another status.

`GET /executions/{execution_id}` is the only read that returns the steps. A listing drops them, because up to a thousand of them per execution would make a page of fifty almost entirely steps, and what a list needs instead is how far the execution got. On a listing that is `reported_count` against `step_count`, beside `status`, which separates the cases a reader has: never taken up, taken up and not started, running, closed having reported everything, and closed having not.

On a read, a step nothing has reported carries a null outcome, which is a different fact from `Skipped`. Skipped means the execution reached that step and passed it over; null means nothing was ever said about it.

## Why the execution summary holds a set and not a counter

Every other projection in this repository writes absolute values, so a replayed batch is harmless by construction: a status derived from an event type is the same value however many times it is written. Progress through an execution is not a value of that kind.

Delivery into a projection is at-least-once, because the worker advances its bookmark in the same transaction as the writes and a crash between the two replays the batch. A column incremented per step would count a replayed step twice and report an execution further along than it is, which is the one lie a record of an abandoned execution must not tell.

So the row holds the set of step indices reported and each step event unions one into it. A union is idempotent where an increment is not, and the count a caller reads is the size of the set.

## An execution cannot check the run its step caused

A run's genesis checks the plan it cites exists, and that check is the whole of what the genesis does. The equivalent is unavailable one scale up, and the reason is worth stating rather than discovering.

A driver reports an acquisition step the moment its engine returns. Whatever watches that engine files the run on its own schedule, as a different process. Nothing orders the two, so at the instant the step is reported the run it caused may not be recorded here yet. A check would refuse the common case.

So the engine's name for the run rides the step as something to resolve later, which is what `docs/reference/client-contract.md` already says such a reference is: a correlation hint rather than a key anything is checked against. An execution's record of an acquisition is a weaker statement than a run's record of a plan, and no amount of ordering the writes fixes it.

## Why Plan and Run share a context

A run cannot exist without the plan it ran, and checking one against the other is the whole of what a run's genesis does. Across a context boundary that check would have to reach through a sibling's read-side surface for a relationship neither side can be without, so the two stay together.

An execution is here for the shape rather than for that check, since an execution cites nothing. Splitting it out would put a procedure and its execution in one context and a plan and its run in another, which separates a pair from its twin and then draws the boundary across the busiest question there is: which runs did this execution cause.

## Reported first

The near-term direction is **reported**: an engine runs the routine, and afterwards someone or something tells this system that it did. **Conducted**, where this system drives the act across an adapter, comes after.

Reported, and deliberately not witnessed, which was the first word here. To witness something is to have been present and able to vouch for it. This system was neither: it is told, by an HTTP caller today and by an adapter draining an engine's output later, and in both cases the whole of what it knows is that it was told. The caller could be wrong. Nothing here can check. "Witnessed" would claim otherwise, and this tree refuses unbacked claims everywhere else.

The word also has to be exclusive with its partner, and "recorded" is not: a conducted run is written into the record too. Reported passes both tests.

There is no field naming the axis, and there is not going to be one. Reporting a run and conducting one are different commands, and the naming rule in [Naming](../reference/naming.md) makes each derive its own genesis event. Which event opened a stream is what says who drove the act.

That is worth more than tidiness. A field can be set wrong, and the project this chassis came from needed a structural test forbidding a reported genesis from claiming it had conducted the act. Two event classes cannot be set wrong. The distinction stops being something to check and becomes something there is no way to write, which is the same move the Policy aggregate makes by holding pairs instead of two independent lists.

The ordering also picks the verb. A slice named `start_run` would claim this system started it, which is the exact claim the axis exists to deny, so the reported genesis takes its own verb and the claiming one waits for the path that earns it.

### Why the other verbs are bare imperatives anyway

The genesis says `report_run` and the five transitions say `complete_run`, `abort_run`, `fail_run`, `pause_run` and `resume_run`. That looks inconsistent, and it is worth saying plainly that it is deliberate.

Read as instructions, the five are addressed to something this system cannot instruct. Nobody asks a run to fail. What a caller is actually asking is for the record to say what the engine already did, and the request is refusable, which is what keeps it a command rather than an inbound event.

They stay bare for two reasons, both of which are R8 in [Naming](../reference/naming.md).

The first is that the event name wins. `RunCompleted` is unimprovable as a row in a log nobody can edit, and the derivation rule runs command to event, so the honest command `report_run_completion` would drag the row to `RunCompletionReported`. The cheap name bends to the expensive one.

The second is that two of the five will never be contested. Conducting does not command an outcome: even an AROC driving the engine would tell it to start and then be told how it went, so `complete_run` and `fail_run` are reporting verbs permanently. The three that will be contested are `abort_run`, `pause_run` and `resume_run`, because those are things a driver genuinely asks for.

**When that surface lands, the prefix goes on the driving side.**

```
   reporting (today)      driving (later)
   -----------------      ---------------
   report_run             start_run
   pause_run              request_pause
   resume_run             request_resume
   abort_run              request_abort
   complete_run           never
   fail_run               never
```

Engines that support a cooperative pause tend to name the asking rather than the state, so a driving surface here would be borrowing the vocabulary of the thing it drives, which is the right direction for an adapter to borrow in. The two surfaces then coexist on one stream as two kinds of event, one recording that somebody asked and one recording what happened, which is the shape Temporal uses for the same problem.

## Where the code is

```
   apps/api/src/aroc/execution/
     aggregates/plan/           state, events, the fold, how to load one, and
                                the summary a list shows with the port over it
     aggregates/procedure/      the same, for a procedure, whose state module
                                also holds the two step kinds
     aggregates/run/            the same, for a run
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the tables in step with the log,
                                and the call that hands them to the worker
     features/
       define_plan/             command, decision, handler, route, tool
       get_plan/                a query slice, so no decider: reading decides nothing
       list_plans/              the queries a fold cannot serve, one per
       define_procedure/        with a context module too, for the plans its
                                acquisitions cite, which is several
       get_procedure/           the only read that returns the steps
       list_procedures/
       report_run/              and a context module, for the plan it reads
       get_run/
       list_runs/               aggregate
       complete_run/            the three endings, one slice each
       abort_run/
       fail_run/
       pause_run/               the cycle, one slice each way
       resume_run/
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

The five commands that move an existing run are five near-identical handlers, and they stay that way deliberately. [Layout](../reference/layout.md#bc-root-extras) offers a shared shell at three such slices, this context reached five, and the shell was built and then reverted. The reasoning is recorded there rather than here, because it is a decision about the chassis rather than about runs.

`report_run/context.py` is the first context module in the tree. A decision function is pure and never reads from a store, but this one has to check the parameters against a schema that lives on another stream. So the handler does the reading and hands the loaded plan across as plain data, which is what keeps the decision testable without a store and replayable without one.

`define_procedure/context.py` is the second, and the first to carry more than one sibling. A procedure may acquire several times, so its handler loads each distinct plan once and hands the lot across keyed by id. Once, because a tomography procedure acquiring the same plan at twenty sample positions would otherwise replay that stream twenty times for no new information.

## Two runs can name the same external run

Nothing enforces that `external_ref` is unique across streams, so reporting the same engine run twice makes two records of it. An event-sourced aggregate has no consistency boundary spanning its siblings, so closing this needs one of the two cross-stream patterns in [Patterns](../reference/patterns.md#cross-stream-uniqueness): a derived stream id, which freezes a namespace permanently, or a unique index on the projection.

The projection now exists and the index was still declined. A unique index enforces uniqueness by making the projection drop the duplicate row, so a run that exists in the log would be missing from every listing, and a read model that undercounts runs is worse than one that shows both records. Listing by external reference returns however many there are, which is what lets a caller see the duplicate at all.

The gap is real and not urgent, because the only caller today is a person or a script making one call. It becomes urgent with the first adapter that retries, since a redelivered start is exactly the duplicate this does not catch. That adapter is the trigger and the right place to decide, because it is the first thing that knows what the natural key actually is.

The idempotency key does not close it. That wrapper keys on what one caller sent, so it catches a retried request and not a re-reported run.

## What is not here yet

The port an engine's lifecycle is observed over, and the adapter that speaks to a real one. Until that exists, every transition here arrives because somebody called an endpoint.

Anything about a pause beyond the fact of it. How long a run has been paused, how many times it has, and what it is waiting for are all answerable from the events and none of them is on the read model. The first caller that needs one is the right place to decide whether it belongs there or in a projection.

Any way to say that a run ended without saying how. The three terminals assume the engine knows which one happened and says so, and the first engine modelled does. A second one, driven in a spike, does not: it writes the same completion string whether the routine finished, the detector timed out or an operator stopped it, so the outcome exists only in a log nothing can read. Against that engine every run would be recorded `Completed`, including the failed ones, and "how many runs failed last week" would be answered confidently and wrongly.

Not decided here, because there is no caller: nothing reports from such an engine today. What the decision would be is a fourth terminal meaning the run is over and the reporter cannot say more, which is the same refusal to overclaim that picked `report` over `witness` above. Worth settling before a second direction is built on this aggregate, because the conducted path doubles what a wrong terminal set costs.

Any way to record a run whose identity does not exist until it ends. `report_run` is a genesis and the five transitions land on what it created, so the shape assumes a caller holding a reference to the run at the moment it starts. The first engine modelled mints one and puts it in the document that opens the stream. The second, driven in the same spike as the terminal question above, has nothing of the kind: its only per-scan identifier is the path of the file it writes, and that path is written by the routine that ends the scan.

```
   an engine that names its run at the start
     start(ref) ---> report_run ---> pause, resume ---> complete
          ^ the reference exists here

   an engine that names it at the end
     start(?) .................................... end(ref)
                                                       ^ and only here
```

That is not a field with the wrong value in it, which is what the terminal question is. It inverts the order this aggregate is built in: such a reporter can only speak once, after the fact, and the five verbs have nothing to attach to in between. Recording the whole run in one call would be a different genesis rather than a variation on this one.

Not decided here, on the same grounds as the terminal question and with the same caveat. Nothing reports from such an engine today. What would settle it is either a genesis that takes a run already ended, or the acceptance that an engine like that is reported as a single terminal fact and the intermediate verbs are simply unavailable to it. The second is cheaper and may be the honest answer; neither should be picked without a caller.

A shared shell for the five update handlers. It was built, measured against the alternative and reverted; see [Layout](../reference/layout.md#bc-root-extras).

Any way to say which plan named `count` is the one to use now. Deliberately unanswered here rather than deferred: a caller resolving a name knows which engine it is speaking to and this system does not, so the mapping belongs with the caller. What would change that is a second caller wanting the same answer for a different reason, at which point the question is a plan lifecycle and worth deciding on its own terms rather than as a lookup.

Anything about where a plan belongs. Nothing on a plan says which installation it was written for, so two plans named `count` for two engines are the same record twice, and "every plan for this installation" is a question nothing here can answer. A reporting caller carries that scope in its own configuration, which holds until something inside this system needs it.

Anything a projection could answer beyond finding a record: how long runs take, how many failed last week, which plan is run most. The tables have the columns for none of those, and each is a column and a filter when somebody asks.

Any search over what a plan constrains. The schema is on the record and on no index, so "which plans take an exposure time" is a question nothing can answer without reading every one.
