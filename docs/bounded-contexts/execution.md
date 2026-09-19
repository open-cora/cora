# Execution

Execution is the bounded context that answers two questions: what can this system be asked to run, and what happened when it ran.

It holds one aggregate for each. The Plan is a runnable routine written down; the Run is one carrying-out of one, as this system came to know about it. Four operations across the two.

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
```

`external_ref` is required. A run this system cannot point back at is a claim that something happened somewhere, with no way to check it or to find the data it produced. Refusing it costs a caller one field and buys every later reader the ability to follow the record to its source.

The parameters are checked against the plan's schema when the record is written, and not again. Re-reading the plan later may find a different schema, which does not make the record wrong: it makes it a record of what was run.

## The four operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Define a plan | `POST /plans` | `define_plan` | `201` with the new id |
| Read one back | `GET /plans/{plan_id}` | `get_plan` | `200` with the plan |
| Report a run | `POST /runs` | `report_run` | `201` with the new id |
| Read one back | `GET /runs/{run_id}` | `get_run` | `200` with the run |

All four are published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `apps/api/src/aroc/execution/routes.py`.

`POST /runs` creates a record of something that already happened, not the happening. The resource being created is the record. A slice that actually starts a run gets its own path rather than a flag on this one, because the two differ in what the caller is asking for and not merely in a field.

Both schemas and parameters come back exactly as they were stored, not re-rendered. A caller generating a form, validating a request locally, or comparing what an engine was given against what it asked for has to be working from the record rather than from a rendering of it.

## What the streams hold

There is no plans table and no runs table. Current state is recomputed by replaying a stream on every read.

```
   PlanDefined   plan_id, plan_name, parameters_schema, occurred_at
   RunReported   run_id, plan_id, parameters,
                 external_ref_scheme, external_ref_value, occurred_at
```

One event each, because nothing changes a plan or ends a run yet. Both arrive as new event classes when the commands that do land, never as fields edited onto these.

The plan's name rides the payload as `plan_name` rather than `name`. The personal-data check reads field names and cannot tell a routine's name from a person's, and an unqualified `name` on an append-only row is the shape that rule exists to stop. The state keeps the bare `name`, where the aggregate it hangs off already supplies the qualifier.

The run's external reference travels as two flat strings and is rebuilt into a pair by the fold, because events carry primitives and that pair is a value object.

## No status on a Run, yet

The point of a run is that it moves, and nothing here moves it. The commands that end a run are not written, so a status would have one reachable value, and a one-valued field says less than no field while suggesting a lifecycle is being enforced.

It lands with the first command that ends a run, derived in the fold from which event the stream carries rather than written onto any payload. The same reasoning kept availability off the Actor until the switch existed, and a status off the Plan until something retires one.

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
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

`InvalidIdentifierError` is the odd one. It belongs to a shared value object rather than to an aggregate, so it does not follow the naming shape the other three do and is not defined in a state module. Nothing else registers a status for it, and unregistered it would be a 500.

A plan that is not there and a plan that refuses the values are deliberately different statuses. One means fix the id, the other means fix the values, and a caller needs to tell them apart.

Names and references are checked twice on the HTTP path, and the two checks answer to different callers. One the request model can refuse never reaches a command and gets FastAPI's own 422; one it cannot, such as a string of spaces, is refused by the value object inside the decision function and gets 400. Neither covers the other's callers, because the MCP surface has no request model.

Reading is gated like writing. A plan says what this system can be asked to run and what a request has to look like, and a run record says what was actually run and with what. Both are things a deployment should get to decide who may see.

## Why Plan and Run share a context

A run cannot exist without the plan it ran, and checking one against the other is the whole of what a run's genesis does. Across a context boundary that check would have to reach through a sibling's read-side surface for a relationship neither side can be without, so the two stay together.

## Reported first

The near-term direction is **reported**: an engine runs the routine, and afterwards someone or something tells this system that it did. **Conducted**, where this system drives the act across an adapter, comes after.

Reported, and deliberately not witnessed, which was the first word here. To witness something is to have been present and able to vouch for it. This system was neither: it is told, by an HTTP caller today and by an adapter draining an engine's output later, and in both cases the whole of what it knows is that it was told. The caller could be wrong. Nothing here can check. "Witnessed" would claim otherwise, and this tree refuses unbacked claims everywhere else.

The word also has to be exclusive with its partner, and "recorded" is not: a conducted run is written into the record too. Reported passes both tests.

There is no field naming the axis, and there is not going to be one. Reporting a run and conducting one are different commands, and the naming rule in [Naming](../reference/naming.md) makes each derive its own genesis event. Which event opened a stream is what says who drove the act.

That is worth more than tidiness. A field can be set wrong, and the project this chassis came from needed a structural test forbidding a reported genesis from claiming it had conducted the act. Two event classes cannot be set wrong. The distinction stops being something to check and becomes something there is no way to write, which is the same move the Policy aggregate makes by holding pairs instead of two independent lists.

The ordering also picks the verb. A slice named `start_run` would claim this system started it, which is the exact claim the axis exists to deny, so the reported genesis takes its own verb and the claiming one waits for the path that earns it.

## Where the code is

```
   apps/api/src/aroc/execution/
     aggregates/plan/           state, events, the fold, and how to load one
     aggregates/run/            the same, for a run
     features/
       define_plan/             command, decision, handler, route, tool
       get_plan/                a query slice, so no decider: reading decides nothing
       report_run/    and a context module, for the plan it reads
       get_run/
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

`report_run/context.py` is the first context module in the tree. A decision function is pure and never reads from a store, but this one has to check the parameters against a schema that lives on another stream. So the handler does the reading and hands the loaded plan across as plain data, which is what keeps the decision testable without a store and replayable without one.

## Two runs can name the same external run

Nothing enforces that `external_ref` is unique across streams, so reporting the same engine run twice makes two records of it. An event-sourced aggregate has no consistency boundary spanning its siblings, so closing this needs one of the two cross-stream patterns in [Patterns](../reference/patterns.md#cross-stream-uniqueness), and both are decisions with consequences: a derived stream id freezes a namespace permanently, and a unique index needs a projection nothing has built.

The gap is real and not urgent, because the only caller today is a person or a script making one call. It becomes urgent with the first adapter that retries, since a redelivered start is exactly the duplicate this does not catch. That adapter is the trigger and the right place to decide, because it is the first thing that knows what the natural key actually is.

The idempotency key does not close it. That wrapper keys on what one caller sent, so it catches a retried request and not a re-reported run.

## What is not here yet

The state machine, which is what makes a run more than a note that something happened. With it come the terminals a run can reach, the pause it can sit in, and the refusals between them.

After that, the port an external engine's lifecycle is observed over, and the adapter that speaks to a real one.

Neither plans nor runs can be listed or searched, only fetched by id. Finding the run matching an external reference is the query the first adapter will want, and a fold cannot serve it: answering would mean replaying every run stream to see which one matches. That needs a maintained summary table rather than a bigger read path.
