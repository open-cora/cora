# Execution

Execution is the bounded context that answers three questions: what can this system be asked to run, what did it compose out of that, and what happened when the composition was carried out.

It holds four aggregates, with a handful of things you can do to each. An Operation names a routine an engine already has. A Procedure is a routine composed here, out of sets and runs in an order. A Setup is the values a beamline applies when it runs one operation, under a name a step can carry. An Execution is one traversal of a procedure.

The difference between an operation and a procedure is who composed the routine. An operation is a reference to a thing this system did not write. A procedure is authored here, and nothing anywhere holds that sequence until the record says so.

**This system owns every genesis.** It writes the operation, composes the procedure, defines the setup and opens the execution. A client outside can only move what the keeper created, which is the posture the whole context is arranged around.

The routine itself still runs outside, in whatever **engine** the deployment has. This context holds what that engine can be asked for, what it was asked for, and what it was reported to have done, never the running of it.

## What an Operation is

An operation is something this system can be asked to run, written down.

```
   Operation
     id                 a UUID minted at definition, never reused
     name               what the engine calls the routine
     parameters_schema  the shape a run of it must supply
     drives_devices     whether a run of it drives devices where it runs,
                        as the facility declared it, or undeclared
     place_use          which of a run's parameters name a place and
                        which name where it processes, as the facility
                        declared it, or undeclared
     status             Active, or Retired once nothing answers to it
```

The name is not decoration: it is how the engine identifies what to run, so an operation without one names nothing and there is no act to record. The status is derived in the fold from which events the stream carries, and [Retiring an operation or a procedure](#retiring-an-operation-or-a-procedure) says what it stops. Device use is declared once by the facility, and [the section below](#device-use-which-the-facility-declares) says what it decides; [place use](#place-use-which-the-facility-declares-too) is declared the same way.

Two operations may share a name and nothing stops that. That follows from what the name is for rather than being a rule of its own. This system identifies an operation by its id everywhere it matters: a run cites an id, and `GET /operations/{operation_id}` reads one back. The name is the handle the engine uses, carried so this system can eventually say which routine to run, and a handle does not have to be unique to do that job.

One routine constrained two ways is two operations, and which one a run cites is what says how it was constrained. Be aware of how little of that difference the record can currently hold: the schema subset has no `items` keyword, so two operations that differ only in which devices they allow are the same document twice, distinguishable by id and nothing else.

## Why the schema is required

An operation carries a JSON Schema, in the constrained subset described in [Conventions](../reference/conventions.md#schema-validated-values), and it is required rather than optional.

The shared carrier-side validator accepts an absent schema and refuses the values that would have gone with it. An operation closes that case earlier, at definition. An operator with nothing to constrain declares a schema that constrains nothing and says so in the record; the alternative is an operation that can never refuse a parameter, with nothing saying whether that was meant.

So of the four cells in that posture table, the absent-schema row is unreachable from here. It stays in the shared helper because the helper is shared and the next declarer may want it.

## Device use, which the facility declares

Whether a run of the operation drives devices at the station that runs it. A collection drives a detector and a stage. A transfer to another facility, or a reconstruction there, drives nothing here and takes hours. Every run composed for a proposal used to claim the devices its adopter or its pursuit named whatever it ran, so a transfer held a station's equipment for as long as it took, and nothing on the record could say otherwise because nothing had been asked.

So the facility says, once per operation, with `declare_operation_device_use`, and the answer is a third state until it does:

```
   drives_devices   a run composed for a proposal

   false            claims no devices and says it drives none, whatever
                    the adopter or the pursuit named
   true             claims the devices its adopter or its pursuit names;
                    an adopter saying it drives none is refused
   undeclared       one run alone takes what its adopter named, exactly
                    as every run did before anything could be declared;
                    one of several runs is refused, naming the operation
```

The rule lives in the composing seam, `keeper.execution.composing`, because adoption and a pursuit's advance both compose through it and the rule is about this context's record. An authored procedure does not pass through it: whoever composes one states each run's devices and is held to [what a run may declare](#what-a-procedure-is), not to the operation's word.

**Undeclared is not a quiet false.** A plan of several runs that cites an operation nobody has declared is refused when it is adopted, with `OperationCannotBeComposedError` naming the operation and the run, so a plan always knows what each of its steps touches. A proposal of one run is not refused, because refusing it would break every proposal already made for an operation nobody has had reason to declare.

**Declared once.** A second declaration is refused whichever way it points, including the way the first one did, and so is a declaration for a retired operation. A wrong answer is corrected the way a wrong schema is, by defining another operation, so every procedure composed under the first declaration still reads as what it was composed under. A caller's own retry is a 409 rather than a success, and the error carries the value already held, which is how that caller sees its first attempt landed.

Who may declare is the deployment's policy rather than anything on the operation. A declaration decides the claims of every run of the routine at every beamline, which is the reason [`infra/deploy/policy_matrix.py`](#who-may-retire-which) gives it to the administrator beside retiring; whether a deployment runs that matrix is read from the deployment.

## Place use, which the facility declares too

Which of a run's parameters name a place. A move names two, where its data leaves and where it lands; a collection may name the place its scan is written; a process names the compute place it runs at, and its input and output are inside that place. A [pursuit](pursuit.md#the-places-it-may-use) names the places its work may use and refuses a round whose runs name any other, and it can only do that if something says which values in a run are places. Nothing here can tell by looking: a parameter is a name and a schema, and `at` holding a place is a convention of the facility's register rather than anything this system reads.

So the facility says, once per operation, with `declare_operation_place_use`, and the answer is two lists of parameter names:

```
   place_parameters           name a place a run reads or writes data at:
                              both ends of a move, where a collection lands
   compute_place_parameters   name where a run processes: where a process
                              runs
```

Either may be empty, which says the routine's runs name no place of that kind, and that is an answer: an operation that only drives devices declares two empty lists. Undeclared is the third state and is refused wherever a run's places have to be known, which today is a pursuit's round closing on a proposal. A run nobody can read the places of could move data anywhere a conductor routes, so it is not read as naming nothing.

Every parameter named must be one the operation's schema declares, as text, because a place is named by text, and a parameter named twice, or named both a place and a compute place, is refused. Each is `InvalidOperationPlaceUseError`, a 400, because no amount of waiting makes such a declaration right for that operation. A parameter a run leaves out names nothing, so a collection that does not say where it lands is checked for its devices alone.

Declared once, refused for a retired operation, corrected by defining another operation, and held by the administrator in the policy matrix, all for the reasons device use gives. The stake is a pursuit's places rather than a station's devices: whoever could declare a move's two ends as naming nothing could carry a pursuit's data anywhere the conductors route.

Nothing here checks a run's places. That is the pursuit's rule, and this context only says which values are places. Adoption outside a pursuit does not ask either, because its caller is a person naming a beamline and devices for one proposal.

## What a Procedure is

A procedure is a routine this system composed: an ordered list of steps, each naming what it touches.

```
   Procedure
     id        a UUID minted at definition, never reused
     name      what this system calls the routine
     beamline  where it runs, such as 2-bm
     steps     sets and runs, in order, each under an id
               minted for it at definition
     status    Active, or Retired once nothing will drive it
```

`beamline` is the routing key. The keeper dispatches an execution and something
at a beamline has to be able to ask for the ones it can drive, which means
"every dispatched execution at 2-bm" has to be a query rather than a read
of every procedure in turn. A dispatch copies it onto the execution, where
that query can reach it.

It is asserted, not derived. A procedure whose steps name `2bmb:m1` can
only run at 2-BM, so this states once what the device addresses already
imply, and parsing the prefix instead would mean this system owning a
grammar that belongs to whatever drives the procedure. It is checked
against nothing, for the reason a scope is: there is no Beamline
aggregate, and a second register of which beamlines exist would be a
thing to keep in step with the beamline descriptors
for no reader's benefit. A word nothing recognises is storable, and shows
up as a dispatch no conductor asks for rather than as a refusal here.

A step is named when it is composed, and that name is what an execution's step cites. Without it the only way to say which definition a step of a traversal came from is its position in two lists. `GET /procedures/{procedure_id}` returns the ids, which is what makes the join something a caller can actually make.

Two kinds of step, and only one of them declares what it touches.

```
   Set       record, to           what it touches is the record it names
   Run       operation_id, parameters, scopes
```

A set sends one record to one value, so deriving what it touches is exact and a declared field would be a second chance to say the same thing differently. A run hands a routine to an engine, and nothing here can see inside that routine to work out which devices it will drive. So a run declares its scopes and a set does not have the option, which is not an inconsistency: one is derivable and the other is not.

A run must either declare at least one scope or say it drives no device. A step that said neither would be one this system believes touches no hardware without anybody having claimed so, and that belief is what lets two of them run at once over one motor. `drives_no_device` is the claim, for work that happens at another facility and has no honest scope to name, and it is refused alongside scopes because the two contradict.

### What a scope is, and what this system does with it

Nothing. A scope is stored as the string it arrived as, and is not parsed into a namespace and a flag. Whatever drives the procedure owns that grammar, the overlap arithmetic runs in that process against its own ledger, and a second implementation here would be two things to keep in step for no reader's benefit. What is checked is that a scope is a non-empty string within a bound, which is what makes it storable.

### Where the parameters are checked

A run's parameters are validated against the schema its operation declares, and the check runs at definition rather than when the procedure is walked. That is earlier and cheaper: a procedure with a malformed run is refused before anything is dispatched, instead of failing partway through a traversal that has already moved motors.

Two gaps in that check are worth stating rather than discovering. A run supplying no parameters at all is accepted whatever its operation requires, because the shared validator defers `required` to the point the values are finally acted on, which is the engine. The one exception is a run of an operation that takes a setup: it has to name one, empty parameters name none, and it is refused for that under [A step checked against the setup it names](#a-step-checked-against-the-setup-it-names). And an operation redefined after the fact does not invalidate a procedure citing it: the parameters were checked against the schema as it stood, and the record is a record of what was composed. An operation retired after the fact leaves the procedure as it was, readable and active, and refuses its dispatch instead.

## What a Setup is

A setup is the values a beamline's conductor applies when it runs an operation, written down under a name a step can carry, with the schema those values satisfy.

```
   Setup
     id               a UUID minted at definition, never reused
     beamline         which beamline holds it, such as 2-bm
     operation_id     the operation it serves
     name             what a step's config parameter carries to name it
     settings         setting name to value, as the conductor applies them
     settings_schema  a JSON Schema describing every setting
     revision         1 at definition, one more for each revision
```

A step names one through the operation it runs. An operation takes a setup when its parameters declare both `config`, which names the setup, and `override`, which writes over some of its settings for one run. Both are required: a `config` with no `override` names values a run could never adjust, and an `override` with no `config` adjusts values nothing named. A setup for an operation that declares neither, or only one, is refused, and so is one for an operation that has been retired.

So a hundred runs with one set of processing flags repeat none of them, and the record of each still says which set it was asked to use: the name is in the step's parameters, and the values are here.

### One per beamline, per operation, by name

The values belong to a place and a routine at once. One processing routine at two beamlines reads two detectors through two sets of optics, so its settings differ by beamline, and one beamline runs several routines whose settings mean nothing to each other. So a setup is keyed on all three, and the same name under another operation or at another beamline is another setup.

The name is where a setup departs from every other record here. An operation's name and a procedure's are labels, two may share one, and the [instance-name convention](../reference/conventions.md#instance-names) says a name is not a key. A setup's name is a key, because it is the only handle a step has: `config` is one of a run's parameters, checked against the operation's schema and against nothing else. So the name is held to the alphabet the facility's operation register puts on `config`, lowercase letters, digits and hyphens, and is not trimmed, because nothing trims a step's `config` before matching it. Every setup can therefore be named by a step.

A second definition under a key already held is refused, naming the setup already there, which is the one to revise. The refusal is a check made before the append and not a lock. An event-sourced aggregate has no consistency boundary spanning its siblings, so two definitions racing each other can both land, and in a deployment the check reads a table a projection fills, so a definition made a moment ago may not be in it yet. What a race leaves is two setups under one key, both in a listing, and a lookup by the key answers with the one defined first. The table's key index is deliberately not unique, because a unique index would hide the second setup rather than refuse it.

### Revised, never edited

Values change: an axis is recalibrated, a filter is swapped. A change is a revision, numbered after the one before it and carrying the whole of the new settings and settings schema rather than a difference. `GET /setups/{setup_id}` reads the latest and `?revision=N` reads any earlier one, folded from the stream that far and no further, so an earlier revision reads back exactly as it was written.

An edit in place would leave whatever used the old values pointing at values nobody can read back. A revision that changes nothing is refused, compared by JSON's equality rather than Python's, so a setting turned from `1` into `true` counts as a change.

A revision names the revision it was made against, as `expected_revision`, and is refused unless that is still the latest. The number is the one a read handed back, so a caller that fetched revision 2 while somebody else wrote revision 3 sends a revision made against 2, and is refused with a 409 that names both numbers rather than landing its values over 3's. Its next move is to read the setup again and decide again. Without the check, 3 would stay readable and its change would be gone from the setup, discarded by somebody who never saw it. The stale check comes before the documents are read, because a revision decided against old values cannot be answered whatever it says.

That guards the window between a caller's read and its revision. The window between the handler's own read and its write is the event store's: the handler appends at the version it folded, so two revisions made against the latest at the same moment leave one revision and one `ConcurrencyError`, also a 409. A replayed revision meets the first guard, since the revision it replays has already moved the setup past the number it carries, which is why revising takes no `Idempotency-Key`.

A revision is held to everything the first revision was: its settings schema and settings are checked exactly as a definition checks them. What it does not ask is whether the operation is still offered, because a revision names no operation. Whatever cites a retired operation is refused where it cites it.

### Why the values are held here and not only their schema

A schema alone would let this system check a step's overrides and nothing more. The values would live in a file on whichever host runs a conductor, and two things would follow: each host would hold its own copy, kept in step with the others by nobody, and the record of a run would name the set it was asked for while the values behind that name sat somewhere this system cannot read.

Held here, a conductor can read a step's setup from the keeper along with its work, no host needs a setups file, and the record says what a run was asked for down to the value.

The settings schema is required for the reason an operation's `parameters_schema` is, and named to pair with it: the family noun and a descriptor, the way [Naming](../reference/naming.md#r3-family-noun-primacy-with-the-role-as-an-adjective-prefix) draws a schema. It is a JSON Schema in the [constrained subset](../reference/conventions.md#schema-validated-values), describing an object with one typed property per setting. That subset cannot close an object, since it has no keyword refusing an undeclared property, so a setup closes it by comparing keys: a setting the schema does not describe is refused, and so is a described setting given no value.

### Who may define and revise one

A setup belongs to a beamline, so writing one is fenced the way composing a procedure is. Defining one asks the gate about the beamline the command names; revising one reads the setup first and asks about the beamline written on it, the way retiring a procedure does. A grant for 19-BM does not write 2-BM's values. Reading and listing are gated like every other read here, and are not fenced.

### A step checked against the setup it names

A run of an operation that takes a setup has to name one, and the name has to mean something where the run will happen. Three things are asked of such a run's parameters:

```
   config     names a setup held for the run's operation at the procedure's beamline
   override   holds only settings that setup's settings schema describes
              (absent is the same as empty)
              and each of them satisfies its description
```

The override is checked as a partial object: the setup's own descriptions with nothing required, because the setup already holds a value for every setting it describes and an override writes over some of them for one run. The keys are compared first, for the reason the settings are: the schema subset has no keyword that refuses an undescribed key. A run of an operation that takes no setup is asked none of this.

The question is asked at three moments, and they differ in what happens to the answer.

```
   when                       resolved at                 refused with
   defining a procedure       the procedure's beamline    InvalidProcedureParametersError, 400
   dispatching an execution   the procedure's beamline    SetupCannotBePinnedError, 409
   adopting a proposal        the adopted beamline,       InvalidProcedureParametersError, 400
                              or the pursuit's
```

**Defining a procedure** resolves each name at the procedure's beamline, at the setup's latest revision, and refuses a run that fails as its parameters, with the step's index and a reason naming the setup, the beamline and the setting. The operation's schema is asked first: an override that is not even the object the operation declares hears about that, not about the setup it was meant for.

**Dispatching** resolves the same names again, at the same beamline, and checks each override against the revision latest now rather than the one the procedure was defined beside. A refusal is a 409 rather than a 400. The step was accepted when it was defined; what it names has since gone, or been revised so the override no longer fits, and the same dispatch goes through once somebody defines the setup or revises it again. Resolving by name at dispatch is also what lets a procedure from before setups were checked be dispatched: it is refused while nothing holds the name it carries, and not after.

A dispatch that passes writes down what it settled. `ExecutionSetupsPinned` goes in the same append as the genesis, with one entry per step that takes a setup: the dispatched step's id, the setup's id and the revision. The revision stops moving for that execution there, so a revision made afterwards changes nothing a step of it was asked to run with. A procedure none of whose runs takes a setup is dispatched exactly as before, with no second event, and reads exactly like one dispatched before setups existed. The read carries the pin on each step, as `setup` holding the setup's id and the revision, or null where the step took none. The values are read from the setup, at that revision.

**Adopting a proposal** composes a procedure around its runs, one or several, and dispatches it in one transaction, so both checks run there for every run, at the beamline the adoption names, or at the pursuit's when a pursuit round advances. One run refused refuses the whole plan. The definition's check runs first and refuses first, which makes a name the beamline does not hold a 400 there, as a procedure's parameters would be. A proposal is made without a beamline, so nothing checks the name it carries when it is made; [Counsel](counsel.md#the-setup-a-proposal-names-is-checked-where-it-is-adopted) says why that is the right place to wait.

None of the three is a lock. A name is found through the summary a projection keeps, which lags the log by the time a definition takes to reach it, so a setup defined a moment ago may not be found yet, and the request is refused as though nobody had defined it; asking again a moment later finds it. The revision is folded from the setup's own stream, which does not lag. A revision landing between that read and the append is not seen, which is the window a definition and a dispatch accept for every sibling they read.

Neither execution table hears the pin. The execution summary keeps a status and what a conductor filters on, and the pin moves neither: it lands in the append that opens the execution and says nothing about how far it got. The step summary is there to find runs nothing filed a dataset for, which a pin does not answer either. So the pin is read where the rest of a step's record is, from the execution's stream.

## The operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Define an operation | `POST /operations` | `define_operation` | `201` with the new id |
| Read one back | `GET /operations/{operation_id}` | `get_operation` | `200` with the operation |
| Find operations | `GET /operations` | `list_operations` | `200` with a page of operations |
| Nothing answers to it any longer | `POST /operations/{operation_id}/retire` | `retire_operation` | `204` |
| Say whether its runs drive devices | `POST /operations/{operation_id}/device-use` | `declare_operation_device_use` | `204` |
| Say which of its parameters name places | `POST /operations/{operation_id}/place-use` | `declare_operation_place_use` | `204` |
| Define a procedure | `POST /procedures` | `define_procedure` | `201` with the new id |
| Read one back | `GET /procedures/{procedure_id}` | `get_procedure` | `200` with the procedure and its steps |
| Find procedures | `GET /procedures` | `list_procedures` | `200` with a page of procedures |
| Nothing will drive it any longer | `POST /procedures/{procedure_id}/retire` | `retire_procedure` | `204` |
| Define a setup | `POST /setups` | `define_setup` | `201` with the new id |
| Read one back, at any revision | `GET /setups/{setup_id}` | `get_setup` | `200` with the setup at one revision |
| Find setups | `GET /setups` | `list_setups` | `200` with a page of setups |
| Its values changed | `POST /setups/{setup_id}/revisions` | `revise_setup` | `201` with the revision number |
| Dispatch an execution | `POST /executions` | `dispatch_execution` | `201` with the new id |
| Something took it up | `POST /executions/{execution_id}/claim` | `claim_execution` | `204` |
| One of its steps ended | `POST /executions/{execution_id}/steps` | `report_step` | `204` |
| An engine moved a step's run | `POST /executions/{execution_id}/steps/{step_id}/run` | `report_step_run` | `204` |
| It stopped at work still running elsewhere | `POST /executions/{execution_id}/park` | `park_execution` | `204` |
| Nothing more is coming | `POST /executions/{execution_id}/end` | `end_execution` | `204` |
| Read one back | `GET /executions/{execution_id}` | `get_execution` | `200` with the execution and its steps |
| Find executions | `GET /executions` | `list_executions` | `200` with a page of executions |
| Find runs nothing filed | `GET /steps/without-datasets` | `list_steps_without_datasets` | `200` with a page of steps |

Each is published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `src/keeper/execution/routes.py`.

The five operations that move an existing execution take an optional `occurred_at`. The four that mint a record do not: defining an operation, composing a procedure, defining a setup and dispatching an execution all happen here, at the moment the record is written, so there is no earlier instant for a caller to report. Neither do the two retirements, the two declarations or a setup's revision, for the same reason. That split is R8's, and it is explained under [When a report says it happened](#when-a-report-says-it-happened) below.

The engine report is the odd endpoint: a step in the path and the verb in the body, where every other transition here puts the verb in the path. The difference is what the caller is. A driver calls one endpoint per thing it means; a reporter drains an engine's document stream and turns each document into whichever of six it is, so a path per verb would make it build a URL by lookup where a field costs it nothing.

Schemas, parameters and settings all come back exactly as they were stored, not re-rendered. A caller generating a form, validating a request locally, or comparing what an engine was given against what it asked for has to be working from the record rather than from a rendering of it.

## What the streams hold

There is no operations table, no setups table and no executions table. Current state is recomputed by replaying a stream on every read.

There are four derived tables, one per aggregate, and none holds state the fold does not. See [Finding one without its id](#finding-one-without-its-id).

```
   OperationDefined        operation_id, operation_name, parameters_schema, occurred_at
   OperationDeviceUseDeclared  operation_id, drives_devices, occurred_at
   OperationPlaceUseDeclared   operation_id, place_parameters,
                               compute_place_parameters, occurred_at
   OperationRetired        operation_id, occurred_at

   ProcedureDefined   procedure_id, procedure_name, beamline, steps, occurred_at
   ProcedureRetired   procedure_id, occurred_at

   SetupDefined       setup_id, beamline, operation_id, setup_name,
                      settings, settings_schema, occurred_at
   SetupRevised       setup_id, revision, settings, settings_schema, occurred_at

   ExecutionDispatched  execution_id, procedure_id, procedure_name,
                        beamline, steps, occurred_at
   ExecutionSetupsPinned  execution_id, pins (step_id, setup_id, revision),
                          occurred_at
   ExecutionClaimed     execution_id, occurred_at
   ExecutionStepDone    execution_id, index, engine_reference, occurred_at
                        (the reference is carried and no longer read)
   ExecutionStepRefused execution_id, index, occurred_at
   ExecutionStepBroken  execution_id, index, cause, occurred_at
   ExecutionStepSkipped execution_id, index, occurred_at
   ExecutionStepHandedOff  execution_id, index, engine_reference, occurred_at
   ExecutionStepEngine*    execution_id, step_id, occurred_at,
                           and engine_reference on Started alone
   ExecutionParked      execution_id, occurred_at
   ExecutionEnded       execution_id, occurred_at
```

`ExecutionStepEngine*` stands for six classes, one per thing an engine can be reported to have done: started, paused, resumed, completed, aborted, failed. Six classes and not one carrying a verb, because an event in a log nobody can edit should not need reading twice, and the command that produces them does carry the verb, because a command is refusable and an event is not.

A step outcome is addressed by index and an engine report by step id, which looks inconsistent and is not. A driver walks the list it was handed and knows where it is; whatever watches an engine knows only the id a driver carried into that engine's metadata.

Two events on a procedure: the genesis, and the retirement that may follow it. An operation has those two and, between them, a declaration of device use and one of place use, at most one of each. A retirement is a class of its own rather than a field edited onto the genesis, and it carries the id and the moment and nothing else, so no reason for it reaches a table nothing can edit. Each declaration is a class of its own for the same reason a pin is: an operation defined before the question could be asked is still a definition, and a genesis carrying an optional answer would be two shapes of one event.

A setup's stream is a genesis and then any number of revisions, each carrying the whole of its settings and settings schema. A revision carries its number and the genesis does not, and neither carries the revision a command was made against: the decider refuses any but the one before, so it is always derivable from the number already on the row. The genesis is revision 1 by definition, so a number there could only agree with the class it sits on. A revision's number is what lets a reader of one row say which revision it is without counting the rows before it, and what lets the summary write an absolute value a replayed batch writes the same way twice, where adding one per revision would count a replay twice. The fold counts the revisions too and compares the two, so a row out of order stops the fold rather than being believed.

`ExecutionSetupsPinned` follows the genesis in the same append when at least one step takes a setup, and is absent when none does. It is a class of its own rather than a field on the genesis for the reason a retirement is: a new fact is a new event, and a genesis written before setups existed would otherwise be a second shape of the same event, told apart by what its payload lacks. See [A step checked against the setup it names](#a-step-checked-against-the-setup-it-names).

A procedure's whole step list rides its genesis, as a list of objects rather than flat fields, which makes it the only payload here holding a nested structure. Each step carries a `kind` discriminating a set from a run. That key is on the wire and not on either class in the model, because there the class IS the kind and a field saying so again is a second thing to get wrong.

Every event after the genesis carries the same two fields. What is running is already on the stream, so a later event adds when, and which thing happened, and nothing else.

Neither the pause nor the resume says why. A pause raised by a signal, by an operator, and by the routine asking for one itself all arrive as the same fact, because stopped versus not is the distinction this system can act on and the rest is the engine's to keep.

The operation's name rides the payload as `operation_name` rather than `name`, and a setup's as `setup_name`. The personal-data check reads field names and cannot tell a routine's name from a person's, and an unqualified `name` on an append-only row is the shape that rule exists to stop. The state keeps the bare `name`, where the aggregate it hangs off already supplies the qualifier.

A dispatched step travels as three fields: its id, the sentence rendered for a reader, and the operation it runs. The sentence is for display and the operation is what anything outside reads, which is why both are there when one of them contains the other as text.

## The state machine

An execution has one, and so does the run an engine opens for one of its run steps. They are two machines on one stream, and keeping them apart is the whole of the section below on two observers.

```
        dispatch_execution
                │
                ▼
         ┌────────────┐  claim_execution  ┌─────────┐
         │ Dispatched │ ────────────────► │ Claimed │ ◄────────────────┐
         └────────────┘                   └────┬────┘                  │
                                               │  a step, or an engine │
                                               │  report, is relayed   │
                                               ▼                       │
                                          ┌─────────┐ park_execution   │
                                          │ Running │ ─────────────┐   │
                                          └────┬────┘              ▼   │
                                               │             ┌────────┐│
                                               │             │ Parked ││
                                               │             └───┬────┘│
                                               │                 │ an engine report
                                               │                 │ ends the step it
                                               │                 ▼ parked at
                                               │             ┌───────┐ │
                                               │             │ Ready │─┘ claim_execution
                                               │             └───────┘
                                               │  end_execution, from any live status
                                               ▼
                                          ┌─────────┐
                                          │  Ended  │
                                          └─────────┘

   a claim, from anything but Dispatched or Ready     refused, 409
   parking, unless the last step reported was
     handed off and the execution is not parked       refused, 409
   a step report while Parked                         refused, 409
   anything at all after Ended                        refused, 409
   a step reported twice                              refused, 409
```

Five live statuses and one terminal. `Dispatched` is the first genuine transient in this tree, and it is one on purpose: an execution exists from the instant it is handed out, and nothing is driving it until something says so. Everywhere else in this repository there is no moment where a command has arrived and its event has not, because a handler decides and appends in one call. That stops being true the moment this system dispatches.

A second claim is what two drivers believing they own one traversal looks like, and refusing it is what makes the disagreement visible. Nothing here can stop the second driver moving a motor; what it can do is refuse to record that the execution was taken up twice.

`Dispatched` standing for a week says nothing was ever claimed. It does not say the dispatch failed, and telling those apart needs something watching the clock rather than another value. An execution whose driver died partway shows as `Running` with fewer steps reported than it holds, and stays that way.

`Parked` is the case that looked like that and is not. A step whose work outlasts what its driver waits for is reported handed off, and the driver parks the execution rather than ending it: the steps after it were written on the assumption that the work finishes, so the walk waits for it rather than guessing. Those steps carry no outcome, because nothing has reached them yet. `Ready` follows when whatever watches the far side reports the handed-off step's run ended, any of the three ways, and a driver then claims the execution and continues from the step after. See [Parked, and why it is not abandoned](#parked-and-why-it-is-not-abandoned) below.

`status` is not stored. The fold derives it from which events the stream carries, so it cannot disagree with the history behind it.

### The engine's own machine, one scale down

```
                report Started
                      │
                      ▼
               ┌───────────┐   report Paused   ┌────────┐
               │  Running  │ ────────────────► │ Paused │
               │           │ ◄──────────────── │        │
               └─────┬─────┘   report Resumed  └───┬────┘
                     │                             │
                     └──────────────┬──────────────┘
                                    │
              Completed        Aborted          Failed
                     │              │                │
                     ▼              ▼                ▼
               ┌───────────┐  ┌─────────┐      ┌────────┐
               │ Completed │  │ Aborted │      │ Failed │
               └───────────┘  └─────────┘      └────────┘

   a report that does not follow the one before it   refused, 409
```

Five states and six reports, and the extra report is the reason they are separate types. A resume puts the run back into `Running`, so a caller sending the state alone would be saying the same word for opening a run and for carrying one on, and this system would have to infer which from what it already held.

All three endings are reachable from `Paused` as well as from `Running`, which is the edge most easily got wrong. A paused engine is exactly the one an operator aborts.

Three terminals rather than one with a reason beside it, because the engines this system is built to hear from report exactly these three, and a reader should not have to parse a string to recover a distinction the source already drew. They split by who or what ended the run: itself, someone else, or a fault.

Nothing carries a reason. A free-text reason is the field most likely to end up holding something about a person, in the one table that cannot be edited, and an engine's failure message is exactly that kind of text. `ActorDeactivated` carries none for the same reason.

A report that does not follow is a 409 and not a 400, and that correction was made for the caller this endpoint exists for. A reporter draining a document stream re-sends the same stop after any restart, so a redelivery is the expected case; as a 400 it was indistinguishable from the reporter sending something malformed, which is the difference between an outcome to move past and an alert.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidOperationNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidOperationParametersSchemaError` | 400 | Not a Draft 2020-12 document, or outside the stored subset. |
| `InvalidOperationPlaceUseError` | 400 | A declaration of place use named a parameter twice, as a place and a compute place both, or one the operation's schema does not declare as text. |
| `InvalidProcedureNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidProcedureStepsError` | 400 | No steps, too many, a set naming no record or sent to a value JSON cannot carry, a run declaring no devices and not saying it drives none, or one that does both. At adoption the bound itself is refused for doing both, whatever its runs drive. |
| `InvalidProcedureParametersError` | 400 | A run's parameters do not satisfy the operation it cites, or name a setup the procedure's beamline does not hold, or override that setup with a setting it does not describe or a value its description refuses. Raised by a definition and by an adoption. Names which step. |
| `InvalidSetupNameError` | 400 | Over the length bound, or outside the lowercase letters, digits and hyphens a step's `config` accepts. Not trimmed first. |
| `InvalidSetupBeamlineError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidSetupSettingsSchemaError` | 400 | Not a Draft 2020-12 document in the stored subset, not an object, describing no setting, or describing one with no type. |
| `InvalidSetupSettingsError` | 400 | A setting the schema does not describe, a described setting with no value, or a value the schema refuses. Names the settings. |
| `InvalidExecutionProcedureNameError` | 400 | The procedure's name falls outside what an execution stores. |
| `InvalidExecutionStepsError` | 400 | The rendered step list is empty, too long, or holds a blank step. |
| `InvalidStepReportError` | 400 | A step report carried a detail belonging to a different outcome, or a break named no cause. |
| `InvalidIdentifierError` | 400 | An external reference had an empty or over-long half. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `OperationNotFoundError` | 404 | The id names no operation, whether the caller asked to read one or cited one in a procedure. |
| `ProcedureNotFoundError` | 404 | The id names no procedure, or a dispatch cited one that does not exist. |
| `ExecutionNotFoundError` | 404 | The id names no execution. |
| `ExecutionStepOutOfRangeError` | 404 | The index is past the end of the list the genesis fixed. |
| `ExecutionStepNotFoundError` | 404 | The same mistake made by id rather than by index. |
| `SetupNotFoundError` | 404 | The id names no setup. |
| `SetupRevisionNotFoundError` | 404 | The setup has not reached the revision a read asked for. Says how far it goes. |
| `OperationAlreadyExistsError` | 409 | Definition was aimed at an id that already has a history. |
| `ProcedureAlreadyExistsError` | 409 | The same, for a procedure. |
| `ExecutionAlreadyExistsError` | 409 | The same, for a dispatch. |
| `SetupAlreadyExistsError` | 409 | Another setup already holds this name for this operation at this beamline, or the definition was aimed at a live stream. Names the setup to revise instead. |
| `OperationCannotBeRetiredError` | 409 | The operation is already retired. Carries the status. |
| `ProcedureCannotBeRetiredError` | 409 | The same, for a procedure. |
| `OperationCannotBeCitedError` | 409 | Something new named a retired operation: a procedure's run, a proposal or a plan, the adoption of one, a setup for it, or a dispatch of a procedure that runs it. Carries the status. |
| `OperationDeviceUseCannotBeDeclaredError` | 409 | A declaration of device use arrived for an operation that is retired, or declared already, whichever way. Carries the status and the value held, which tell the two apart. |
| `OperationPlaceUseCannotBeDeclaredError` | 409 | A declaration of place use arrived for an operation that is retired, or declared already, whatever it said. Carries the status and the declaration held. |
| `OperationCannotBeComposedError` | 409 | A run composed for a proposal met its operation's device use: undeclared, in a plan of several runs, or declared to drive devices while its adopter said it drives none. Names the operation and the run, and carries the declaration it met. |
| `OperationCannotTakeSetupError` | 409 | A setup was defined for an operation whose parameters do not declare both `config` and `override`. |
| `SetupCannotBeRevisedError` | 409 | The revision was made against a revision that is no longer the latest, or its settings and settings schema are the current revision's already. Carries both numbers, which tell the two apart. |
| `ProcedureCannotBeDispatchedError` | 409 | The dispatch named a retired procedure. Carries the status. |
| `SetupCannotBePinnedError` | 409 | A run the dispatch would hand out names a setup the procedure's beamline does not hold, or its override no longer fits that setup's latest revision. Names the step, the setup, the beamline and the setting. |
| `ExecutionCannotBeClaimedError` | 409 | The execution is not waiting to be taken up: something already claimed it, it is parked on work still running, or it ended. Carries the status. |
| `ExecutionCannotBeParkedError` | 409 | A parking arrived for an execution parked or ready already, or one whose last reported step handed nothing off to wait on. Carries the status and that step's outcome, which tell the two apart. |
| `ExecutionAlreadyEndedError` | 409 | A step report, a parking or a close arrived for an execution that had already closed. |
| `ExecutionStepAlreadyReportedError` | 409 | That step already has an outcome, and a step ends exactly once. |
| `ExecutionStepCannotBeReportedError` | 409 | A step was reported for an execution that is parked, waiting on work a step handed off. A claim takes it back once it is ready. Carries the status. |
| `StepRunCannotBeReportedError` | 409 | The engine report does not follow the engine state already recorded. Carries both. |
| `ConcurrencyError` | 409 | The execution or the setup changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

One table, where there were two. The second existed because the execution refusals had been left out of the first and adding them in place would have buried the distinction between an aggregate this system is told about and one it drives. Every aggregate here is now one this system drives, so there is one kind of record and one table.

`InvalidIdentifierError` is the odd one. It belongs to a shared value object rather than to an aggregate, so it does not follow the naming shape the other three do and is not defined in a state module. Nothing else registers a status for it, and unregistered it would be a 500.

`StepRunCannotBeReportedError` is one class covering a whole state machine. R6 is about not collapsing several VERBS into one class, and this is one slice taking a discriminator, so the verb is a value rather than a call site, and five classes would be five names for one refusal nobody could tell apart by type. The error carries the state it holds and the report it got.

`ExecutionCannotBeClaimedError` carries the status for the same reason: being told an execution cannot be claimed is much less useful than being told something already claimed it, which is a contest, or that it ended, which is merely late.

An operation that is not there and an operation that refuses the values are deliberately different statuses. One means fix the id, the other means fix the values, and a caller needs to tell them apart.

Names and references are checked twice on the HTTP path, and the two checks answer to different callers. One the request model can refuse never reaches a command and gets FastAPI's own 422; one it cannot, such as a string of spaces, is refused by the value object inside the decision function and gets 400. Neither covers the other's callers, because the MCP surface has no request model.

Reading is gated like writing. An operation says what this system can be asked to run and what a request has to look like; a procedure says what it was asked to do and to which devices; an execution says what happened. All three are things a deployment should get to decide who may see.

## When a report says it happened

The five commands that move an existing execution accept an optional `occurred_at`, and a caller who omits it gets the moment their report arrived.

This matters most where it is easiest to overlook. For a driver reporting live, the gap between when a step ended and when this system heard is milliseconds. For a reporter that was down for an hour it is an hour. For a backfill out of an engine's own archive it is years, and without this field every one of those would be recorded as having happened on the afternoon somebody ran the import.

**Which commands take the field is itself the claim.** The four that mint a record do not, and the asymmetry is the point. Defining an operation, composing a procedure, defining a setup and dispatching an execution are acts this system performs: the moment it writes one is the moment it exists. A step being driven and an engine opening a run for it happened somewhere else. That is R8 in [Naming](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one), and the split now runs through one aggregate rather than between two.

A supplied timestamp must carry an offset and is stored as UTC. It is not checked against anything else: not against the clock, not against the execution's own genesis. A step may therefore claim to have finished before the execution was dispatched.

That is not laxness, it is the same posture the rest of this context takes. An engine's `exit_status` is not second-guessed either. What is promised is that the record says plainly what was claimed, and separately says when it was written down, and the second of those is written by the database rather than by this application, so no caller can touch it. See the Time section in [Conventions](../reference/conventions.md#time) for the full reasoning.

A list row carries both timestamps and a single read carries neither, which is a decision on each side rather than an oversight on one. A list is read to find something, and when an execution ran is how a person recognises the one they meant. A single read already names it, so the question is answered before the timestamps could help.

## Retiring an operation or a procedure

An operation is retired when no engine answers to it any longer, and a procedure when nothing will drive it. Before either could be, a routine the facility had moved away from stayed in the record looking exactly like one that worked, and a dispatch of it was recorded and then waited forever, which reads the same as an execution that is merely waiting.

Retiring is not deleting. The stream stays, a read by id still answers with a `status` of `Retired`, and every procedure and execution that cites the record still resolves it. What changes is what may rest on it next:

```
   a retired operation   a procedure whose run cites it     refused, 409
                         a proposal or a plan for it        refused, 409
                         adopting a proposal for it         refused, 409
                         a setup for it                     refused, 409
                         declaring its device use           refused, 409
                         declaring its place use            refused, 409
                         dispatching a procedure that
                           runs it                          refused, 409
   a retired procedure   dispatching it                     refused, 409
```

The refusals are in the deciders, which read the status off the state each handler already hands them. That is what makes them hold for adoption too: adopting a proposal composes a procedure and dispatches it through `compose_runs`, which calls the same two deciders without passing through either handler, and asks about retirement itself first so that a run is never refused over a device use that can no longer be declared.

Retiring an operation is enough on its own to stop every procedure that runs it from being dispatched. Nobody has to find each of those procedures first, and retiring them as well tidies the listings rather than closing anything.

What it does not touch is work already handed out. An execution dispatched before the retirement stays dispatched, because retiring says what may be handed out next and an execution that exists was handed out already; one nobody will ever claim is the orphaned-execution question, which this does not answer. A retirement that lands between a dispatch's read and its append is not seen by that dispatch, which is accepted for the reason a definition accepts the same of an operation it read.

There is no unretire. A routine that comes back is defined again, and a procedure around it is composed again, which keeps every execution pointing at what it actually ran.

### Who may retire which

A procedure carries the beamline it was composed for, so retiring one is fenced the way defining one is: the gate is asked about the procedure's own beamline, and a grant for 19-BM does not retire 2-BM's routines. The beamline is written on the procedure and nowhere else, so this is the one handler here that reads before it authorizes. A refused caller learns first whether an id names a procedure, which is the price of fencing by a fact the record holds rather than one the caller repeats.

An operation is one value for the whole facility. Retiring one reaches every beamline that cites it, and there is no beamline to fence it by, so the command carries none. In `infra/deploy/policy_matrix.py` it is the administrator's alone; whether a deployment runs that matrix is read from the deployment, not from this page.

### Why a listing leaves them out

`GET /operations` and `GET /procedures` leave retired rows out unless `include_retired=true` is passed, and every row carries its `status` either way.

The siblings do not do this. A device listing shows a retired device and an execution listing shows an ended one, because a listing there answers what is, and those are part of it. A listing here answers what can be run, and a retired routine cannot be. Showing it by default would leave every caller that resolves a name to filter it out again, and the one that forgot would compose around it or dispatch it and be refused.

It would also undo one reason to retire an operation: a name defined twice, where the second should have been the only one. Retiring the older leaves one row under that name, and only a listing that leaves the older out shows that.

## Finding one without its id

Four reads in this context name what they want. `GET /operations/{operation_id}`, `GET /procedures/{procedure_id}`, `GET /setups/{setup_id}` and `GET /executions/{execution_id}` replay one stream each and answer from it, which costs one query and stays correct forever because the stream is the record.

Five questions cannot be answered that way: which operations answer to a name, which procedures do, which setup a beamline holds under a name for an operation, which executions were dispatched for one procedure, and which are waiting at one beamline. Answering any of them would mean replaying every stream of its kind to see which ones match. A fold needs to know which stream to fold, and that is exactly what is being asked.

So there is a second read path:

```
   POST /operations                 GET /operations/{operation_id}
   POST /procedures                 GET /procedures/{procedure_id}
   POST /setups                     GET /setups/{setup_id}
   POST /executions                 GET /executions/{execution_id}
     |                                fold a stream each. Unchanged.
     | event
     v
   events  (the record)             GET /operations?name=...
     |                              GET /procedures?name=...
     | one worker, a bookmark each  GET /setups?name=...
     v                              GET /executions?procedure_id=...
   proj_execution_operation_summary   read the tables below
   proj_execution_procedure_summary
   proj_execution_setup_summary
   proj_execution_execution_summary
```

Three things about it are worth knowing before reading a row.

**It lags.** `POST /executions` returns before the row exists. Normally tens of milliseconds, never zero. A caller that writes and immediately lists may not see what it just wrote.

**It can be thrown away.** Every column is derived from the event log, so dropping the table and resetting its bookmark to zero rebuilds it exactly. The log is the record; this is a convenience over it. That is why these tables take full `UPDATE` and `DELETE` while `events` does not.

**It is not a second way to write.** Nothing but the worker writes a row. A handler that wrote one directly would be inventing a fact the log does not hold.

There is a port per aggregate, each declared with the aggregate it summarises, and two implementations of each. A deployment reads the table. An environment with no database folds every stream of that kind instead, which is the expensive thing the table exists to avoid and is free when the whole store is a dictionary. A shared contract suite per port runs against both of its sides, because the two sides share no code and the claim that they answer alike is otherwise just prose.

**The procedure index is not unique, and that is the ordinary case.** A routine composed once is executed every time it runs, so many executions under one procedure is what a deployment looks like rather than a duplicate. A unique constraint there would refuse the second run of anything.

**A setup's key is the one lookup expected to return one row.** The definition refuses a second setup under a key already held, so `GET /setups` with all three filters answers with one setup, or with two where a race got past that check, and the listing is where a person sees the second. The defining handler asks the same question through the port before it writes, and that lookup returns the one defined first.

**An operation name is where the questions differ.** An operation's name is not an identity: it is the engine's handle, and this system holds operations for every engine it hears from. So `GET /operations?name=count` returns however many there are, and it is a way to see them rather than a way to choose between them.

Choosing is the caller's, and a caller that has to choose holds a mapping rather than applies a rule. Something composing procedures for one engine knows which installation it serves and which operation each name means there; this system knows neither, and nothing on the two records would tell it apart if it tried. A lookup returning one of two would be making that choice on every call, silently, on the strength of an ordering nobody asked about.

## What an Execution is

An execution is one traversal of a procedure: the record this system opens when it dispatches one, and how far the thing driving it got.

```
   Execution
     id              a UUID minted when the record is written
     procedure_id    the routine that was dispatched
     procedure_name  its name, copied at dispatch
     beamline        where it runs, copied at dispatch
     steps           each with its own id: what it was asked to
                     perform, the setup revision it was pinned to,
                     and how each ended
     status          Dispatched, Claimed, Running, Parked, Ready or
                     Ended
```

`beamline` is the one field here that exists for a query rather than for
a reader. A conductor asks for every dispatched execution at its own
beamline, which is a filter over many rows, so the value has to be on the
row rather than one reference away. That is what separates it from an id a
step could carry instead: an id answers one reader's question about one row
with the whole definition a hop away, and this selects the page.

Each step carries an id of its own, minted at dispatch and written onto the genesis. It is on the payload rather than made during the fold because a fold has to produce the same steps on every replay, and a record other aggregates point at cannot move between them.

A step has an id at all so that something outside can name one. A dataset is produced by one run, not by a whole traversal, so `(execution_id, index)` would be a pointer into the interior of another aggregate rather than a handle: it cannot be fetched, and checking it exists means folding the whole execution and bounds-checking an integer. Both [Custody](custody.md) and [Counsel](counsel.md) now cite one.

**A step also cites the composed step it came from**, and that arrived with the second consumer rather than the first. Custody only needed a step to exist, so an id was enough. Counsel needs to ask something about one, whether it ran the operation a proposal named, and nothing on the record could answer: the operation id was present only inside the rendered sentence, written for a person to read.

```
   Procedure R1                    Execution E1, on Tuesday
     T1  set 2bmb:m1 to 0.0   <------  S1  from T1
     T2  run operation P1     <------  S2  from T2
           exposure 0.25
           touches 2bmb:det:         Execution E2, on Wednesday
                              <------  S3  from T1
                              <------  S4  from T2
```

Two ids on one step, and they are not interchangeable. `S2` names this traversal's step, which is what Custody and Counsel point at, and `T2` names the definition every traversal of the procedure shares. They cannot be collapsed, because one procedure is dispatched many times.

**The first shape of this copied the operation id onto the step instead.** It worked and it was replaced, because a copy answers one consumer's one question and the next question needs the next field, a payload key and a migration each. A citation answers all of them: the operation, the parameters the step was composed with, and the devices it declares are all on the definition. The alternative to both was a positional join against the procedure's own step list, built by one zip in one decider and asserted nowhere.

Rot is what a copy would buy, and there is none to buy. Nothing edits a procedure's steps, retiring it included, so a citation that resolved once resolves forever, and changing a routine means composing another one.

An execution cites its procedure and still copies its name and its steps' descriptions. That copy is not redundancy. The fold is pure and cannot load another stream, so the length of the step list has to ride the genesis for the outcomes to have anywhere to land, and once the count is there the sentences cost one string each and keep the record readable on its own.

### Why an execution has a status when nothing else here does

Every other aggregate in this repository is free of transient states, because there is no moment where a command has arrived and its event has not. That holds for a record of something somebody else did. It stops holding the moment this system dispatches.

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

`Dispatched` is the first genuine transient in this tree, and it is one on purpose. A row sitting there with an old timestamp says nothing ever took the work up, which is a different failure from a driver that died partway: that one reads as `Running` with steps unreported. Nothing here can tell either from something merely slow, which is the limit Conducting names rather than papers over.

The drawing leaves out the two statuses a parked walk passes through, which the state machine above draws. `Parked` and `Ready` sit between `Running` and the claim that takes a walk back, and an ending is accepted from either.

Claiming is refused from every status but `Dispatched`, which makes it the only command on this stream that refuses from a live status as well as the terminal one. A second claim is two drivers each believing they own one traversal. Nothing here can stop the second from moving a motor; what it can do is refuse to record that the execution was taken up twice, so the disagreement ends up in the log rather than only at the beamline.

Claiming is not a gate on reporting. A driver that reports a step without claiming first moves the execution straight from `Dispatched` to `Running`, and that is allowed: a claim says who has the work, and refusing the report would lose a fact this system was told in order to enforce an ordering the log does not have.

### No reference of its own

An earlier shape had the driver mint a name for the execution before its first step, because at that moment there was no handle to refer to. Under a dispatch there is: this system creates the record first, so the execution's id is the handle, and it is the id a driver carries into whatever it asks an engine to run.

Each step ends exactly once, in one of five ways:

```
   Done       the seam returned, which is not the same as the step working
   Refused    a claim conflict stopped it before it touched anything
   Broken     the seam raised
   Skipped    the execution had already stopped before reaching it
   HandedOff  the work was accepted somewhere else and had not finished
              when the driver stopped waiting
```

`HandedOff` is terminal in a narrower sense than the other four, and the difference matters to anyone reading a record that holds one. The other four are written once the step is over. This one is written while the work is still running: the driver waited as long as its deployment allows, stopped, and said where the work went. Nothing will report that step again, because the walk stopped there: it parks, and a driver that takes it back starts from the step after.

What happened next is not missing from the record, it is on the other axis. An engine report against the same step says how the work finished, sent by whatever watches that engine rather than by whatever drove the step. The reference the outcome carries is what joins the two, which is why it is the one detail this outcome requires and a done step may omit. That report is also what makes a parked execution ready.

### Two observers of one step, kept apart

A run step gets talked about twice, by two clients that do not know about each other.

```
   outcome        what the driver saw     Done, Refused, Broken, Skipped, HandedOff
   engine_state   what the engine said    Running, Paused, Completed, Aborted, Failed
```

They are two fields because they can disagree, and the disagreement is the point. A run whose data a second writer corrupted can still end in the engine's own word for success, so neither observer is reliable and collapsing the two would make this system pick a winner between claims it cannot check. A step whose call returned while its engine reported a failure reads as `Done` and `Failed`, which is the honest record.

A set carries no engine state at all, because a set opens no run for anything to watch.

The five engine values are deliberately the five a run has. It is the same engine reporting the same lifecycle one scale down, and a reader who has learned one should not have to learn a second vocabulary for it. The transitions are the same too: all three endings are reachable from `Paused` as well as from `Running`, a resume is the only edge pointing backwards, and nothing follows an ending.

Neither account waits for the other. A driver may report its call returning before or after the engine reports the run ending, so requiring an order would refuse whichever arrived first. An engine's account is accepted even after an execution has been closed, because a driver that gave up does not stop the hardware from having done something, and that account is the only record of what it did.

`Done` is the word most likely to be read as more than it is. A run whose data was corrupted can still report success, so the outcome says the call returned and nothing about whether the science worked. `Refused` is the only unambiguously good news in the set.

An outcome carries at most one detail, and two of the five carry none. A done step may name the run it opened, a broken step names the class that was raised, and a handed-off step must name the work still running. A refused step names nothing, and a skipped step never could.

Two outcomes share the reference field and need it under different rules. A done step may omit it, because a set opens no run and there is nothing left to ask about. A handed-off step may not, because the reference is the only way anything learns how the work ended: without one the record says something began somewhere and gives no way to find it.

That a refusal says nothing about the conflict is a boundary rather than a gap. Which step was holding the device, and which scopes collided, are facts about a ledger that lives in the driver's own process and is not durable by its own argument. Nothing here can act on either, and an append-only table is the wrong home for another process's working notes. A driver that wants to explain a refusal to a person has the ledger in front of it.

There is no value meaning abandoned. An execution whose driver died reads as `Running` with steps unreported and stays that way, because saying more needs something watching rather than another status.

### Parked, and why it is not abandoned

A parked execution has stopped and said why, which is the whole difference. Its driver reported a step handed off and then parked the execution, so the record holds a fact a dead driver could never write: the walk is waiting on work still running elsewhere, and will be taken back.

`Ready` is derived and never reported. Nothing outside says an execution is ready; whatever watches the far side reports the handed-off step's run ending, on the axis it always used, and the fold reads that report against the step the execution parked at. The step it parked at is the last one reported, which parking requires to be handed off and which no step report can move while it is parked. An ending against any other step, such as a late one for a run that finished inside its bound, releases nothing.

Any of the three endings makes it ready, because ready means a driver may take it back and not that the work went well. A driver that finds the work did not complete reports the rest as skipped and closes the execution, so a failed handoff leaves the record a walk left before parking existed, only later. Continuing on a failure is a different question, and it is the next round's to answer rather than this walk's.

The ending can arrive before the parking. The driver reports the handed-off step and parks in two requests, and a watcher can land between them; parking then finds the ending already recorded and the execution is ready at once, rather than waiting for a report that has come and gone.

A walk that hands off its last step parks too. Ending it at the handoff would read as finished while the last of its work was still running, and a pursuit that opens a round on an ended execution would then ask about work nobody can yet say anything about.

Nothing holds a device while an execution is parked. A step's claim lasts as long as its call, handoff included, so the steps after a parked one take their own claims when a driver reaches them. That is what lets a conductor walk something else while a transfer runs, and it is the same exposure a scan past its bound already had: the stage is still turning, and nothing claims it.

`GET /executions/{execution_id}` is the only read that returns the steps. A listing drops them, because up to a thousand of them per execution would make a page of fifty almost entirely steps, and what a list needs instead is how far the execution got. On a listing that is `reported_count` against `step_count`, beside `status`, which separates the cases a reader has: never taken up, taken up and not started, running, closed having reported everything, and closed having not.

On a read, a step nothing has reported carries a null outcome, which is a different fact from `Skipped`. Skipped means the execution reached that step and passed it over; null means nothing was ever said about it.

## Why the execution summary holds a set and not a counter

Every other projection in this repository writes absolute values, so a replayed batch is harmless by construction: a status derived from an event type is the same value however many times it is written. Progress through an execution is not a value of that kind.

Delivery into a projection is at-least-once, because the worker advances its bookmark in the same transaction as the writes and a crash between the two replays the batch. A column incremented per step would count a replayed step twice and report an execution further along than it is, which is the one lie a record of an abandoned execution must not tell.

So the row holds the set of step indices reported and each step event unions one into it. A union is idempotent where an increment is not, and the count a caller reads is the size of the set.

The same reasoning holds the two columns that tell a parked execution from a ready one. The fold has every step in hand and reads the step a parking waits on directly; the table has one event at a time, and the two reports name steps differently, a step report by index and an engine report by id. So the row keeps the genesis step ids in their order, which pairs the two, and the set of step ids an engine report has ended, unioned like the indices, which lets a parking find an ending that landed before it.

## The one query expected to run continuously

`GET /executions?beamline=2-bm&status=Dispatched&runs=tomoScan_2BM` is how something at a beamline finds work the keeper has dispatched, nothing has taken up, and it can actually run. A conductor asks the same question with `status=Ready` first, unheld, for a parked walk whose wait is over: ready before dispatched, so a plan in flight finishes before new work starts. It is the only read here that a machine makes on a loop rather than a person makes on a question, which is why `(beamline, status)` carries an index of its own and why all three parts are on the summary row rather than one reference away.

The first two filters are needed and neither is enough. A beamline alone returns work already being driven; a status alone returns three other beamlines' work. Claiming either by mistake would mean a conductor driving hardware it does not own, and a claim is a write with no command to take it back.

The third is the same argument about the engine rather than the hardware. A conductor that claims a routine it cannot run drives nothing, which is the hardware safe, and still spends the execution: the step is refused, the walk ends, and whatever could have driven it never sees the work again. So `routines` is copied onto the row at dispatch, off the operations the procedure's run steps cite, and the filter is a subset test. A row comes back when every routine it needs is one the caller runs, because a claim is taken once for the whole traversal and running some of the steps is no better than running none.

Both empty cases fall out of the subset rather than being written. A procedure of sets alone needs no engine, so it is offered to every caller; a conductor with no engine sends the empty set and is offered only those. The parameter being absent is a third thing again, and it means do not narrow, which is what a person browsing wants and what the MCP tool always sends.

No index for the routines. The intake index narrows to one beamline's dispatched rows first, which is a handful, so the array test is a recheck over those rather than a scan.

**The request can be held open.** `wait` turns the query into a long poll: rather than answering an empty page, the keeper holds the request until a dispatch appears for that beamline or the wait runs out. An idle conductor then sits on one open connection and re-opens it every thirty seconds, instead of asking every few seconds and almost always being told nothing, and work reaches it in milliseconds rather than at the next tick.

The bound is a socket keepalive ceiling and not a latency budget. A connection held indefinitely dies in a proxy or a NAT table without telling either end, so the request returns empty at the ceiling and the caller opens another. A dispatch landing in that gap is not lost: it is sitting at `Dispatched`, and the next request returns it.

What wakes a held request is a Postgres `NOTIFY` fired by a trigger on the summary table, not the one on `events` that the projection worker listens to. An event landing is not yet a row this query can answer from, and a request woken by that one would find the worker still mid-transaction. `dispatch_signal.py` holds the argument.

The signal is a latency optimization and never the answer. A notify can arrive while nothing is listening, or between a reader's query and its next wait, so each wait inside a held request is itself bounded and the query runs again after it. A missed signal costs a slower pickup, never a dispatch nobody takes up.

The answer is a page and not a single execution, and nothing reserves a row for the asker. Two conductors reading the same page is expected, and what keeps them apart is the claim: `POST /executions/{execution_id}/claim` is refused from every status but `DISPATCHED` and `READY`, so the second one gets a 409 and moves on. The mutual exclusion is the event store's optimistic concurrency rather than anything this query does.

The ready ask is never held, and the reason is the trigger. It fires when a row is inserted, which is a dispatch, and a parked execution becomes ready by an update. A held request woken by that update would be asking for dispatched work and find none, so nothing fires for it, and a conductor finds ready work at its next ask: at once after a walk, and at most one held wait later when it is idle. A transfer that took an hour can afford thirty seconds.

## An execution cannot check the engine run its step opened

A procedure's genesis checks that every operation it cites exists, and that check is real. The equivalent one scale down is unavailable, and the reason is worth stating rather than discovering.

Whatever watches an engine reports the name it gave a run, on a start. Nothing here can ask that engine whether such a run exists, and nothing holds a record of it to check against. So `engine_reference` is a correlation hint rather than a key, which is what `docs/reference/client-contract.md` already says such a reference is.

A driver used to report it too, on a `Done`, and the field is still on that event because drivers still send it. It is no longer folded into the step. Driving a step says how the call went and nothing about what the engine called the run: the value a driver holds is whatever its own call returned, which is proximity rather than knowledge, and the same value is readable by anything watching. Reading both also let arrival order decide the answer, because the driver's report lands after the watcher's and would replace a true reference with a stale one, or with nothing at all. The field comes off the event once no deployed driver sends one.

That is weaker than an operation reference and it is the honest shape. An engine's names are the engine's, and a system that claimed to have checked one would be claiming to have asked.

## Why the four share a context

A run step cannot be composed without the operation it cites, and checking one against the other is the whole of what a procedure's genesis does. A setup cannot be defined without the operation it serves, because whether that operation's parameters can name a setup at all is the first thing its definition asks. A dispatch cannot open a record without copying the procedure it hands out. Across a context boundary each of those would have to reach through a sibling's read-side surface for a relationship neither side can be without, so the four stay together.

## This system owns every genesis

This context is **dispatched** rather than **reported**: it composes the work and hands it out, and what comes back is how it went. Nothing an outside caller sends brings a record into existence.

That is the decision the whole page is arranged around. It is what makes every id in play one this system minted, so there is nothing to resolve by external reference and no way for two records to answer to one engine run.

What still comes from outside is how the work went, on two channels that can disagree, and neither is treated as the other's correction. That is the section above on two observers.

**Reported is the right word for those two channels**, and deliberately not witnessed. To witness something is to have been present and able to vouch for it. This system is neither: it is told, and the whole of what it knows is that it was told. The caller could be wrong and nothing here can check. "Witnessed" would claim otherwise, and this tree refuses unbacked claims everywhere else.

### Why the verbs are bare imperatives

The commands say `claim_execution`, `report_step`, `report_step_run`, `park_execution` and `end_execution`, and the mixture is deliberate.

Three of them name the act plainly, because it is an act: claiming an execution, parking one and ending one are things a caller does here, and the record is made by the doing.

The other two are reports, and say so. Read as instructions, they would be addressed to something this system cannot instruct. Nobody asks a step to break. What a caller is asking is for the record to say what already happened, and the request is refusable, which is what keeps it a command rather than an inbound event.

**There is one driving verb and it is `dispatch_execution`.** This system dispatches a whole procedure and a conductor carries it out step by step, so there is no per-step driving verb to pair against each reporting one.

What a driving surface would still add is the asking side of a pause, which is a request to a conductor rather than a report about an engine. That belongs to the conductor's own intake, not here, and Conducting is where it is discussed.

## Where the code is

```
   src/keeper/execution/
     aggregates/operation/           state, events, the fold, how to load one, and
                                the summary a list shows with the port over it
     aggregates/procedure/      the same, for a procedure, whose state module
                                also holds the two step kinds
     aggregates/setup/          the same, for a setup, whose fold also keeps
                                every revision it passes through
     aggregates/execution/      the same, for an execution, whose state module
                                holds the step, both its observers and two enums
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the tables in step with the log,
                                and the call that hands them to the worker
     features/
       define_operation/             command, decision, handler, route, tool
       get_operation/                a query slice, so no decider: reading decides nothing
       list_operations/              the queries a fold cannot serve, one per
       retire_operation/        the transition that stops an operation being offered
       declare_operation_device_use/  made once, and decides what a composed run claims
       declare_operation_place_use/   made once, and says which of a run's values are places
       define_procedure/        with a context module too, for the operations its
                                runs cite, which is several
       get_procedure/           the only read that returns the typed steps
       list_procedures/         aggregate
       retire_procedure/        reads the procedure before the gate, for its beamline
       define_setup/            with a context module, for the operation it serves
                                and the setup already holding its key
       get_setup/               the only read that returns settings and their schema
       list_setups/
       revise_setup/            reads the setup before the gate, for its beamline
       dispatch_execution/      with a context module, for the procedure it copies
       claim_execution/
       report_step/             one slice, five outcomes on a discriminator
       report_step_run/         one slice, six reports on a discriminator
       park_execution/          stops a walk at work still running
                                elsewhere, until a claim takes it back
       end_execution/
       get_execution/
       list_executions/
       list_steps_without_datasets/  the one read here that also sees Custody
     composing.py               turns a proposal's runs into one procedure and
                                one execution, by each operation's device use,
                                for the two contexts that adopt
     resolving.py               finds the setups runs name, for every caller
                                that checks a run against one
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

**Eight directories went with an aggregate this context no longer has**, and six of those were its transitions: five near-identical handlers plus a genesis. [Layout](../reference/layout.md#bc-root-extras) records a shared shell for them that was built and then reverted, and the decision it records is still the live one, because the same question came up again here and was answered the other way.

`report_step` and `report_step_run` each take a discriminator rather than splitting into four and six slices. That is the reverse of what that aggregate did, and the reason is that the outcome is a value on a refusable command rather than a separate call site: one command that can be refused, several event classes that cannot be set wrong. Thirty near-identical files would have been the wrong trade when the sibling slice on the same stream had already answered it.

`define_procedure/context.py` carries more than one sibling, and is the only context module here that does. A procedure may hold several runs, so its handler loads each distinct operation once and hands the lot across keyed by id. Once, because a tomography procedure running the same operation at twenty sample positions would otherwise replay that stream twenty times for no new information.

## What is not here yet

**A scan run by hand.** An engine run carrying no keeper reference cannot be recorded: there is no execution to hang it on, no step, and no way to make either out of a report. The engine keeps its own record, and a reported shape would be a purely additive change if one is wanted.

Anything about a pause beyond the fact of it. How long an engine has held a step paused, how many times it has, and what it is waiting for are all answerable from the events and none of them is on the read model. The first caller that needs one is the right place to decide whether it belongs there or in a projection.

Any way to say that an engine run ended without saying how. The three terminals assume the engine knows which one happened and says so, and the first engine modelled does. Not every engine does: one may write the same completion string whether the routine finished, the detector timed out or an operator stopped it, so the outcome exists only in a log nothing can read. Against that engine every step would be recorded `Completed`, including the failed ones, and "how many runs failed last week" would be answered confidently and wrongly.

Not decided here, because there is no caller: nothing reports from such an engine today. What the decision would be is a fourth terminal meaning the run is over and the reporter cannot say more, which is the same refusal to overclaim that picked `report` over `witness` above. Worth settling before a second direction is built on this aggregate, because the conducted path doubles what a wrong terminal set costs.

Any way to hear from an engine that names its run only at the end. The engine reference arrives on the `Started` report and every later report is matched to a step by the id a driver carried into the engine's metadata, so the shape assumes a stream that opens with something identifiable. The first engine modelled does that. An engine may have nothing of the kind, with its only per-run identifier the path of a file it writes, and that path written by the routine that ends the run.

```
   an engine that names its run at the start
     start(ref) ---> Started ---> Paused, Resumed ---> Completed
          ^ the reference exists here

   an engine that names it at the end
     start(?) ........................................ end(ref)
                                                          ^ and only here
```

This is less damaging than it was. The reference is a correlation hint rather than a key, so an engine that cannot supply one still has its step reported: what is lost is the ability to join that step to whatever the engine wrote. Recording the whole thing in one call is still not a variation on this shape.

A shared shell for near-identical update handlers. It was built for the five transitions of a since-retired aggregate, measured against the alternative and reverted; see [Layout](../reference/layout.md#bc-root-extras). There are fewer of them to share now, which is a reason the question has not come back rather than an answer to it.

Any way to say which of two active operations named `count` is the one to use now. Retiring narrows the question without answering it: a retired operation is never the one, and a listing leaves it out, but two active operations under one name are still two, and choosing between them is still the caller's. A caller resolving a name knows which engine it is speaking to and this system does not, so the mapping belongs with the caller.

Anything that ends an execution a retirement left behind. One dispatched before its procedure or its operation was retired stays dispatched, and nothing here ends it; that is the orphaned-execution question, and a retirement is not an answer to it.

Anything that notices a parked execution whose work never ends. A transfer retrying a missing file for a day leaves its execution parked for a day, waiting rather than abandoned, and nothing reports it; the staleness read the orphaned-execution question was answered with would show it by its age, once built. Ending it is a person's call, with `end_execution`, which a parked execution takes as any live one does.

Anything about where an operation belongs. Nothing on an operation says which installation it was written for, so two operations named `count` for two engines are the same record twice, and "every operation for this installation" is a question nothing here can answer. Whatever composes procedures carries that scope in its own configuration, which holds until something inside this system needs it.

Anything a projection could answer beyond finding a record: how long executions take, how many steps broke last week, which procedure is dispatched most. The tables have the columns for none of those, and each is a column and a filter when somebody asks.

Any search over what an operation constrains. The schema is on the record and on no index, so "which operations take an exposure time" is a question nothing can answer without reading every one.

A conductor that reads a setup. Holding the values here is what lets one read them with its work, and none does yet, so a run's record can name a setup that nothing applied from here.

Retiring a setup. One defined in error, or for a routine a beamline has stopped running, stays listed beside the ones in use, and nothing says which is which.

Any check of an authored procedure against device use. Someone composing a procedure by hand states each run's devices, and a run of an operation declared to drive none may still name scopes there and claim them. Only runs composed for a proposal follow the declaration, because those are the runs nobody stated anything for.

Any way to take a declaration of device use or of place use back. A wrong one is corrected by defining another operation and retiring the first, which is the honest cost of a value that decides what every later composed run may claim, or which places every later pursuit can read.

Anything that notices two setups under one key. The check a definition makes can be raced, and a race leaves both setups readable and both in a listing, with a lookup by the key answering with the first. Nothing reports that the second exists.
