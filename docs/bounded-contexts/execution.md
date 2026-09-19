# Execution

Execution is the bounded context that answers two questions: what can this system be asked to run, and what happened when it ran.

It holds one aggregate for each. The Plan is a runnable routine written down; the Run is one carrying-out of one, as this system came to know about it. Eleven operations across the two.

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

Two plans may share a name and nothing stops that. One routine constrained two ways is two plans, and which one a run cites is what says how it was constrained.

## Why the schema is required

A plan carries a JSON Schema, in the constrained subset described in [Conventions](../reference/conventions.md#schema-validated-values), and it is required rather than optional.

The shared carrier-side validator accepts an absent schema and refuses the values that would have gone with it. A plan closes that case earlier, at definition. An operator with nothing to constrain declares a schema that constrains nothing and says so in the record; the alternative is a plan that can never refuse a parameter, with nothing saying whether that was meant.

So of the four cells in that posture table, the absent-schema row is unreachable from here. It stays in the shared helper because the helper is shared and the next declarer may want it.

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

## The eleven operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Define a plan | `POST /plans` | `define_plan` | `201` with the new id |
| Read one back | `GET /plans/{plan_id}` | `get_plan` | `200` with the plan |
| Find plans | `GET /plans` | `list_plans` | `200` with a page of plans |
| Report a run | `POST /runs` | `report_run` | `201` with the new id |
| Read one back | `GET /runs/{run_id}` | `get_run` | `200` with the run |
| Find runs | `GET /runs` | `list_runs` | `200` with a page of runs |
| It stopped where it was | `POST /runs/{run_id}/pause` | `pause_run` | `204` |
| It carried on | `POST /runs/{run_id}/resume` | `resume_run` | `204` |
| It reached its end | `POST /runs/{run_id}/complete` | `complete_run` | `204` |
| Something stopped it | `POST /runs/{run_id}/abort` | `abort_run` | `204` |
| It broke | `POST /runs/{run_id}/fail` | `fail_run` | `204` |

All eleven are published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `apps/api/src/aroc/execution/routes.py`.

The six run operations that write take an optional `occurred_at`. The two plan operations do not. That split is R8's, and it is explained under [When a run's transition happened](#when-a-runs-transition-happened) below.

`POST /runs` creates a record of something that already happened, not the happening. The resource being created is the record. A slice that actually starts a run gets its own path rather than a flag on this one, because the two differ in what the caller is asking for and not merely in a field.

Both schemas and parameters come back exactly as they were stored, not re-rendered. A caller generating a form, validating a request locally, or comparing what an engine was given against what it asked for has to be working from the record rather than from a rendering of it.

## What the streams hold

There is no plans table and no runs table. Current state is recomputed by replaying a stream on every read.

There are two derived tables, one per aggregate, and neither holds state the fold does not. See [Finding one without its id](#finding-one-without-its-id).

```
   PlanDefined   plan_id, plan_name, parameters_schema, occurred_at

   RunReported   run_id, plan_id, parameters,
                 external_ref_scheme, external_ref_value, occurred_at
   RunPaused     run_id, occurred_at
   RunResumed    run_id, occurred_at
   RunCompleted  run_id, occurred_at
   RunAborted    run_id, occurred_at
   RunFailed     run_id, occurred_at
```

One event on a plan, because nothing changes one yet. Retiring a plan arrives as a new class when the command that does lands, never as a field edited onto `PlanDefined`.

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
| `InvalidIdentifierError` | 400 | An external reference had an empty or over-long half. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `PlanNotFoundError` | 404 | The id names no plan, whether the caller asked to read one or named one while reporting a run. |
| `RunNotFoundError` | 404 | The id names no run. |
| `PlanAlreadyExistsError` | 409 | Definition was aimed at an id that already has a history. |
| `RunAlreadyExistsError` | 409 | The same, for a run. |
| `RunCannotBeCompletedError` | 409 | The run had already ended. |
| `RunCannotBeAbortedError` | 409 | The same, for an abort. |
| `RunCannotBeFailedError` | 409 | The same, for a failure. |
| `RunCannotBePausedError` | 409 | The run is not running: it had ended, or it was already paused. |
| `RunCannotBeResumedError` | 409 | The run is not paused: it had ended, or it was running all along. |
| `ConcurrencyError` | 409 | The run changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

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

**A plan name is where the two questions differ.** A run's external reference is meant to be unique and merely is not enforced to be. A plan's name is meant to repeat: one routine constrained two ways is two plans. So `GET /plans?name=count` returns however many there are, and choosing between them is the caller's. An operator who wants one answer pins a plan id; a caller that cannot choose should refuse and say so. A lookup returning one of two would be making that choice on every call, silently, on the strength of an ordering nobody asked about.

## Why Plan and Run share a context

A run cannot exist without the plan it ran, and checking one against the other is the whole of what a run's genesis does. Across a context boundary that check would have to reach through a sibling's read-side surface for a relationship neither side can be without, so the two stay together.

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
     aggregates/run/            the same, for a run
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the tables in step with the log
     _projections.py            hands them to the worker at startup
     features/
       define_plan/             command, decision, handler, route, tool
       get_plan/                a query slice, so no decider: reading decides nothing
       list_plans/              the queries a fold cannot serve, one per
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

## Two runs can name the same external run

Nothing enforces that `external_ref` is unique across streams, so reporting the same engine run twice makes two records of it. An event-sourced aggregate has no consistency boundary spanning its siblings, so closing this needs one of the two cross-stream patterns in [Patterns](../reference/patterns.md#cross-stream-uniqueness): a derived stream id, which freezes a namespace permanently, or a unique index on the projection.

The projection now exists and the index was still declined. A unique index enforces uniqueness by making the projection drop the duplicate row, so a run that exists in the log would be missing from every listing, and a read model that undercounts runs is worse than one that shows both records. Listing by external reference returns however many there are, which is what lets a caller see the duplicate at all.

The gap is real and not urgent, because the only caller today is a person or a script making one call. It becomes urgent with the first adapter that retries, since a redelivered start is exactly the duplicate this does not catch. That adapter is the trigger and the right place to decide, because it is the first thing that knows what the natural key actually is.

The idempotency key does not close it. That wrapper keys on what one caller sent, so it catches a retried request and not a re-reported run.

## What is not here yet

The port an engine's lifecycle is observed over, and the adapter that speaks to a real one. Until that exists, every transition here arrives because somebody called an endpoint.

Anything about a pause beyond the fact of it. How long a run has been paused, how many times it has, and what it is waiting for are all answerable from the events and none of them is on the read model. The first caller that needs one is the right place to decide whether it belongs there or in a projection.

A shared shell for the five update handlers. It was built, measured against the alternative and reverted; see [Layout](../reference/layout.md#bc-root-extras).

Any way to say which plan named `count` is the one to use now. Listing them is answered; choosing between them is not, and closing it would mean a plan that can be superseded. That is a lifecycle this context does not have, and it should not grow one before a caller asks.

Anything a projection could answer beyond finding a record: how long runs take, how many failed last week, which plan is run most. The tables have the columns for none of those, and each is a column and a filter when somebody asks.

Any search over what a plan constrains. The schema is on the record and on no index, so "which plans take an exposure time" is a question nothing can answer without reading every one.
