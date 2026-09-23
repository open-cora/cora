# blueapi findings

Measured against blueapi 1.20.0, bluesky 1.15.1, event-model 1.23.1 and
RabbitMQ 4.3.6 with its STOMP plugin on. Numbers below are from
`findings.json`, which `probe.py` wrote.

The headline is that blueapi does the thing queueserver could not, and
publishes a successful run for a plan that failed. The submit-time handle
reaches the run's permanent record, which settles the identity question
that `spikes/queueserver_adapter/` closed the other way. And the plan-level
and run-level accounts of one task can disagree, legitimately, in the
direction that makes a document-only reporter wrong.

## 1. No queue, and the API says so in two words

Submitting and starting are separate calls. A second submission while the
worker is busy is accepted; starting it is refused.

```
   worker state while running        "RUNNING"
   submitting a second task          201, {"task_id": "a4c34882-..."}
   starting it while busy            409, {"detail": "Worker already active"}
```

ADR 0003 is literally true rather than aspirational. Submitted tasks
accumulate as pending and **nothing advances them**: six tracked, one
still pending, and it stayed pending until something made it active. This
is a task registry, not a queue with the automatic bit disabled.

For a conductor that matters twice. The refusal is distinguishable by
status code, which is what `Refused` needs and what an exception type
could carry. But the detail names no holder: to find out which task owns
the worker, a client has to ask `GET /worker/task` separately. Queueserver's
refusal carried the holder and a free-text note in the message itself, and
that was the better ergonomics of the two.

There is no lock API, at all. Searching the served OpenAPI for "lock"
returns nothing. Coordination is entirely the caller's, which is the whole
point of the decision and the reason this composes with `claims.py`
instead of competing with it.

## 2. A caller cannot carry its own reference, and does not need to

`TaskRequest` sets `additionalProperties: false`, so the obvious move is
refused:

```
   POST /tasks with metadata={"aroc_directive_id": "directive-1"}

   422  extra_forbidden  "Extra inputs are not permitted"  loc: body.metadata
```

There is no field for it. `Task` has a `metadata` property and the request
model does not expose it, so the mechanism commit e246acf relies on has no
door here.

What replaces it is better than what queueserver offered. The service fills
that metadata itself, and it reaches the run:

```
   start document keys   uid, time, versions, user, instrument_session,
                         blueapi_task_id, scan_id, plan_type, plan_name, ...

   blueapi_task_id in the start document   True
   the task_id POST /tasks returned        f12ccb1d-1ea5-4282-b885-95076bd6a340
   run uid                                 65e1a908-6631-4ff1-a8ba-bafb83ae72ac
```

**This is the thing queueserver does not do.** Section 1 of those findings
measured an `item_uid` that appears nowhere a document reader can see, and
concluded it could never be the join. Here the submit-time handle is in the
start document, so a client knows the name before the run exists and a
reporter watching the stream records runs under something that name can
find. Both halves, one identifier.

Two costs. It is blueapi's name rather than AROC's, so the conductor's own
reference does not appear on the engine's permanent record at all, and
`ReferenceNotCarriedError` has nothing to check. And the join would then
depend on a particular service being in front of the engine, where the run
uid does not.

`instrument_session` is mandatory on every task and reaches the start
document too. It is Diamond's visit identifier and there is no way to omit
it. A facility with proposal and ESAF numbers, which is what
`spikes/tomoscan_adapter/` found in the PV set, would be putting one of
them in a field named for somebody else's scheme.

## 3. The reporter's translator survives; only a source is new

Documents arrive on the bus in a three-key envelope:

```json
{"name": "start", "doc": {"uid": "...", "...": "..."}, "task_id": "f12ccb1d-..."}
```

`doc` is an unmodified event-model document, so `translate.py` works on it
untouched. What is new is `sources.py`: a STOMP subscriber rather than a
0MQ one, and one that discriminates two envelope shapes, because worker
events share the topic:

```
   envelope keys seen on /topic/public.worker.event
     documents      name, doc, task_id
     worker events  state, task_status, errors, warnings

   documents in one run   start, descriptor, event, stop
```

That is the same split `spikes/tomoscan_adapter/` section 5 already asked
for, arriving from a second direction: `Session` should take an intent and
the translator should move out to the caller. Doing that makes this source
a small addition rather than a second code path through `Session`.

Headers are worth a note because the documentation points at the wrong
one. The events page names `correlation-id` under STOMP. On the start
message the headers were:

```
   subscription, destination, message-id, redelivered,
   JMSType, traceparent, content-length
```

`traceparent` is there, W3C trace context, and `correlation-id` is not.
The task id does appear in a header on some messages and in the document
body on all of them, so the durable path in section 2 is the one to use
rather than a header that is not always present.

## 4. It runs with none of Diamond's stack

The config in this directory has no oidc, no tiled, no numtracker, no opa
and no device source. Diamond's own system-test config carries all five.
The service started anyway and served:

```
   plans registered     quick_count, slow_count, failing_count
   devices registered   (none, and nothing needed one)
   GET /healthz         200
   GET /config/oidc     204, empty body
```

Plans are registered by introspecting type hints into pydantic schemas,
which is the package's stated selling point and works exactly as
advertised: a plain module on `PYTHONPATH` with three annotated functions
in it, and no dodal, no device manager and no Kubernetes.

So Diamond's stack is Diamond's deployment rather than the package's
requirements, with one exception. `instrument_session` is not optional,
and that one is baked into the request model.

## 5. A plan that failed published a run that succeeded

This is the finding. `failing_count` opens a run, reads a detector twice,
and raises after the run closes.

```
   REST outcome          {"outcome": "error", "type": "RuntimeError",
                          "message": "the spike asked this plan to fail"}
   task_failed           True
   errors                ["the spike asked this plan to fail"]

   stop document         exit_status "success",  reason ""
```

The run did succeed. The plan did not. Both statements are true, because
they are about different objects, and blueapi's events page says so in
advance: there is a gap between the start of a plan and its first run start
document, the same at the other end, and one plan may hold several runs.

**What it costs AROC is concrete.** `apps/reporter` reads documents. A
reporter watching this bus and translating only the `{name, doc}` envelopes
would record this task's run `Completed`, which is the exact failure shape
`spikes/conductor/` was built around: a confident wrong answer that nothing
downstream can catch. The information exists, on the same topic, in the
worker event carrying `task_failed: true`.

So this is not queueserver's problem, where `history` said `completed` and
the stop document said `success` and somebody had to write a second
mapping table. The two accounts here do not compete. They describe a plan
and a run, and **a reporter needs both** or it is wrong about failures
whose cause lives outside a run.

On the agreeing case, for completeness: a successful `quick_count` gave
`outcome: "success"` and `exit_status: "success"`.

## What this recommends

**Prefer blueapi over queueserver for a multi-client bluesky beamline, and
for a different reason than expected.** The comparison going in put the
weight on its no-queue posture, which does hold and does compose with
`claims.py`. The stronger reason turned out to be section 2: a submit-time
handle that is in the run's permanent record is what the conducting work
has wanted since e246acf, and queueserver's is measured not to be.

**The join should stay the run uid anyway.** `blueapi_task_id` is better
than `item_uid` by a wide margin, and it still ties AROC's identity to one
service being deployed. The run uid is in the start document under every
engine that publishes documents at all. Use `blueapi_task_id` as the
submit-time handle a conductor holds while a task runs, and keep the join
where it is.

**A reporter on this bus must read worker events, not only documents.**
Section 5. This is not optional and it is not an optimisation; a
document-only reporter reports failures as successes here.

**`ReferenceNotCarriedError` has no job under blueapi.** There is no way to
put the conductor's reference into the engine's record, so the check has
nothing to compare. That is a loss worth naming: the conductor's name stops
appearing in the data catalogue, and the only thing tying a run to the walk
that caused it becomes blueapi's task id plus whatever AROC records itself.

**Someone has to decide what `instrument_session` holds at APS.** It is
mandatory, it reaches the permanent record, and the obvious candidates are
the proposal and ESAF numbers that `spikes/tomoscan_adapter/` section 8
flagged as sitting next to named people in the PV set.

## What this spike did not do

It drove no hardware. The plans read `ophyd.sim.det` and no device source
was configured, so nothing here says how blueapi resolves device names,
what `mock: true` changes, or what a real ophyd-async device costs at
environment startup.

It ran one worker with no authentication. Every question about who may
submit, which `instrument_session` a token is allowed to claim, and what
OPA policy does is untouched, and those are most of what a facility would
have to configure.

It did not test `DELETE /environment`, the live-reload path, or what
happens to a running task when the environment is torn down.

The failure in section 5 was raised after the run closed. A plan that
raises with a run still open would presumably stop with `exit_status:
"fail"`, which would make the two accounts agree, and that case was not
driven. What is measured is the case where the failure is outside a run,
which is where setup and cleanup live and therefore common.

It used one STOMP topic on a local broker with guest credentials. Nothing
here says what a shared broker, durable subscriptions or a reconnect do,
and the reporter's own durability gap is unchanged by any of it.
