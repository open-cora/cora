# Findings

What driving a real RunEngine into the real HTTP surface actually showed.
Everything below is from `documents.json` and the two scripts, not from
reading documentation. Where the Bluesky docs disagree with what the wire
did, the wire wins and the disagreement is noted.

Run against bluesky 1.15.1, ophyd 1.11.0, Python 3.13.

## The short version

The **natural key question is settled**, so the projection is unblocked.
The **status mapping is confirmed correct**, including one case the method
names actively mislead about. **Pause and resume are observable, but only
through a channel the Bluesky docs call experimental**, and that makes them
strictly less dependable than the three endings.

Two things the spike surfaced that were not on the question list, and both
matter more than some that were: **an adapter cannot honestly author a
Plan**, and **every timestamp AROC recorded was the wrong one**. The
second has since been fixed; see section 6. So has the restart gap in
section 7, which was on the list and is now closed on both halves: a
restarted reporter recovers its runs and its plans from AROC and holds
nothing it cannot rebuild.

What is left is the redelivery gap in section 7, which is deliberate, and
one modelling question the read side surfaced rather than answered: when
two plans share a name, nothing says which one is current.

## 1. The natural key: settled

`start["uid"]` is a UUID4 minted per run by the engine, and the stop
document points back at it through `run_start`. It is globally unique
without any scoping, so nothing about a deployment, facility or beamline
needs to go into the key.

**Recommendation:** `scheme = "bluesky-run-uid"`, `value = start["uid"]`,
and a unique index on the pair. The scheme is what keeps a different
engine's identifier vocabulary from colliding with this one, which is what
that half of `Identifier` is for.

This is the decision the projection was waiting on. Variant B in
`docs/reference/patterns.md#cross-stream-uniqueness` can be taken with the
index unique from the first migration rather than added later.

## 2. Pause and resume: observable, on the shakiest of the three channels

All three channels were armed at once and all three were watched.

| Channel | Works? | Notes |
| --- | --- | --- |
| `RE.record_interruptions = True` | **yes** | In the document stream. Docs call it experimental and "subject to change or removal". |
| `RE.state_hook` | **yes** | Exists despite being undocumented. Fires `(old, new)`. In-process only. |
| polling `RE.state` | yes | Documented, but polling. |

**The Bluesky docs get the data key wrong.** They say the event carries
`interruptions`. It carries `interruption`, singular; the plural is the
stream and descriptor name. An extractor written from the docs finds
nothing and concludes the channel is dead. It is not dead.

```json
{"data": {"interruption": "pause"},  "seq_num": 1, ...}
{"data": {"interruption": "resume"}, "seq_num": 2, ...}
```

**Recommendation: use `record_interruptions`, not `state_hook`**, despite
the experimental label. The reason is not reliability, it is reach:
`state_hook` is an in-process Python callback, so it is unavailable to any
adapter subscribing to a remote engine over zmq or a message bus, which is
what a real deployment looks like. The document stream is the only channel
that survives the adapter being a separate process.

The cost has to be stated plainly: **pause and resume rest on a flag its
own authors describe as removable.** The three endings do not. If that flag
goes away, `pause_run` and `resume_run` have no feed.

**`state_hook` revealed four states the docs do not list.** The documented
set is idle, running, paused. The real transitions:

```
   completes              idle -> running -> idle
   pause_resume_complete  idle -> running -> pausing -> paused -> running -> idle
   stop_from_pause        idle -> running -> pausing -> paused -> stopping -> idle
   abort_from_pause       idle -> running -> pausing -> paused -> aborting -> idle
   halt_from_pause        idle -> running -> pausing -> paused -> halting -> idle
```

`pausing`, `stopping`, `aborting` and `halting` are all real and all
transient. Anything built on `state_hook` would have to know them; nothing
built on the document stream does. Another point for the document stream.

**Suspenders were not tested.** The interruptions stream has a third value,
`suspend`, which our single `Paused` status would flatten into the same
thing as a pause. Still open.

## 3. Landing 4's `has_ended` fix was load-bearing, and here is the proof

Three of the seven scenarios end from a pause: `stop_from_pause`,
`abort_from_pause`, `halt_from_pause`. Their real document order is
start, pause event, stop.

`has_ended` used to read `status is not RUNNING`. Under that reading a
paused run counted as ended, so all three of those scenarios would have
been refused with 409 at the final step. **Three of seven real engine
behaviours, rejected.** The fix was not hypothetical tidying.

## 4. The exit_status mapping: correct, with one genuine trap

| What a person did | `exit_status` | AROC verb | Status |
| --- | --- | --- | --- |
| plan ran to the end | `success` | `complete` | Completed |
| `RE.stop()` | `success` | `complete` | Completed |
| `RE.abort()` | `abort` | `abort` | Aborted |
| `RE.halt()` | `abort` | `abort` | Aborted |
| plan raised | `fail` | `fail` | Failed |

All seven scenarios reached the expected status, zero refusals.

**The string is `abort`, not `aborted`.** The docs contradict themselves;
the wire says `abort`.

**`halt` is indistinguishable from `abort` by the time it reaches us.**
Five engine actions collapse into three statuses before AROC sees anything,
so our three terminals are not lossy relative to what is observable: they
are exactly as fine-grained as the source. That is the right place to be.

**`RE.stop()` records success.** Worth a comment wherever the mapping is
written down, because "stop" reads like an abort and is not one.

## 5. An adapter cannot honestly author a Plan

This was not on the question list and it is the biggest modelling finding.

A start document describes **one invocation**, not the plan. It carries
`plan_name` and the arguments that call used. It does not carry the plan's
signature, so there is nothing in it from which a correct
`parameters_schema` can be derived. The spike derived one anyway, by typing
whatever values happened to be present, and AROC accepted it, which is
exactly the failure mode: a schema that describes one call and pretends to
constrain all of them.

`plan_args` is also not fit to be `parameters` as it stands:

```json
{"detectors": ["SynGauss(prefix='', name='det', read_attrs=['val'],
                configuration_attrs=['Imax','center','sigma','noise',
                'noise_multiplier'])"],
 "num": 2, "delay": 0.0}
```

The detector entry is a **device repr**, not a name. It is verbose, it
embeds configuration that can change between runs, and it would go
verbatim into a log nobody can edit. The clean names are on a different
key: `start["detectors"] == ["det"]`.

**Recommendations.** Plans are authored out of band, by an operator, from
the plan's real signature. The adapter looks one up by name and refuses a
run whose plan it does not recognise. That means a second missing query,
`get_plan_by_name`, alongside the external-ref lookup. And the adapter
composes `parameters` rather than forwarding `plan_args`: scalar arguments
from `plan_args`, device names from `start["detectors"]`.

**The missing `items` keyword did not block anything.** `{"type": "array"}`
was accepted. It is a weakening, not a wall: a detector list can be
declared an array and nothing more. Lower priority than it looked.

## 6. Every timestamp AROC records was the wrong one (now fixed)

Also not on the question list. Both documents carry `time`, in UNIX
seconds, from the engine. The adapter dropped them, because no endpoint
accepted a timestamp, so `occurred_at` on every event is the moment AROC
was told rather than the moment the thing happened.

For a live adapter that gap is milliseconds. For a backfill, a replay out
of databroker, or a reporter that was down for an hour, it is however long
the delay was, and the record says the run completed when the report
arrived. The envelope already separates `occurred_at` from `recorded_at`,
so the model had the right shape; nothing let a caller set the first one.

**Fixed after this spike reported it.** All six run commands now accept an
optional `occurred_at`, and `replay.py` forwards each document's own
`time`. It must carry an offset and is stored as UTC. It is not checked
against the clock, because `recorded_at` is written by the database and
says truthfully when the row arrived, so an absurd claim is visible next
to the truth rather than refused on the strength of a clock the chassis
documents as able to run backward.

`time` has accordingly dropped out of both lists in section 8, and all
seven scenarios still reach their expected status with no refusals.

## 7. Both read-side gaps, demonstrated rather than argued

**The restart, since fixed on both halves.** The adapter's whole memory
was two dictionaries, Bluesky uid to AROC run id and plan name to AROC
plan id, and neither was recoverable. Cleared them, replayed one stop
document, and the run was unreachable:

```
cannot complete: no run known for uid 5b4f40e7
```

`GET /runs` and `GET /plans` now take a filter on the engine's own
vocabulary, backed by the two projections in the tree, and the same
demonstration recovers both:

```
the run half:  GET /runs by uid gives 01a0ba65-df83-...
               which is the id it held before the restart: True
               replaying the stop document now gets: 409 already Completed

the plan half: GET /plans by name gives 01a0ba65-dfab-...
               which is the id it held before the restart: True
               plans defined before the restart and after: 4, 4
```

The refusal that is left on the run half is the right one and a different
one. It used to be "I cannot find this run"; it is now the domain saying
that ending already happened.

The plan half never produced a refusal, which is what made it the more
dangerous of the two. A restarted adapter simply authored `count` again,
leaving two plans where an operator wrote one and every later run
pointing at whichever the adapter happened to be holding. `4, 4` is the
whole of the fix.

`replay.py` does both lookups the way a real reporter wants them, memory
first and AROC second, in `run_id_for` and `plan_id_for`. The two are not
symmetric and the docstrings say why: a second run under one uid is
somebody recording the same run twice, and a second plan under one name
is the aggregate working as designed.

**What the plan half still cannot answer.** Which of two plans named
`count` an operator means today. The lookup takes the newest because that
is the order the page arrives in, and that is a guess. Nothing in AROC
carries supersession or a current-version flag, so there is no honest
answer to take instead. This is the gap that the next plan-side decision
should close.

**The redelivery, still open.** Replayed one start document that had
already been processed. AROC returned 201 and minted a second run, then a
third, all three recording the same engine run, all accepted:

```
first =01a0b991-89e0-7da3-86f0-39cd8b26690b
second=01a0b991-8a0c-73b3-b33d-83b69fe3d9de
third =01a0b991-8a0e-73e3-a88c-7ef5b02ec244
```

The idempotency key does not help: it scopes to one caller's request, and
after a restart the adapter has no key to resend.

The two gaps meet in the lookup. A restart after that redelivery finds
three runs under one uid:

```
3 runs recorded under uid 5b4f40e7; taking the first
```

Which is deliberate rather than a second defect. The projection carries no
unique index on the reference pair, so the duplicate is visible instead of
swallowed. The alternative, a unique index, enforces uniqueness by
dropping the second row, which would leave a run that exists in the log
missing from every listing. Picking one of the three is the adapter's
policy to state out loud, as it does here, not AROC's to make quietly.

## 8. Everything else with nowhere to go

```
   start:  detectors, hints, num_intervals, num_points,
           plan_type, scan_id, versions
   stop:   num_events, reason, uid
```

Two worth a decision rather than a shrug:

- **`scan_id`**, the human-friendly integer operators actually say out
  loud. Nothing holds it, so a person cannot find their scan by the number
  on their screen.
- **`reason`** on a failed stop, which carried the exception message
  verbatim in scenario 6. We refuse to store it on purpose, and the
  decision looks right: it is free text from an engine, which is exactly
  the field most likely to end up holding something about a person.

## What this changes

1. ~~**The projection is unblocked and can ship unique from day one.**~~
   Shipped, as `proj_execution_run_summary` behind `GET /runs`, with the
   key `("bluesky-run-uid", start["uid"])`. NOT unique; see section 7 for
   why that changed.
2. ~~**It needs a sibling**: a plan lookup by name, or the adapter cannot
   resolve `count` to a plan.~~ Shipped, as `proj_execution_plan_summary`
   behind `GET /plans`. A restarted adapter now recovers both halves of
   its memory; see section 7. What the lookup cannot say is which of two
   plans sharing a name is current, which is a modelling gap rather than
   a missing query.
3. ~~Reconsider whether a caller may supply `occurred_at`.~~ Done, see
   section 6.
4. **Know that pause and resume rest on an experimental flag.** The
   recommendation used to say to write that next to the two slices in the
   Execution docs. That was wrong and the page is now checked against it:
   which engine a deployment runs is a deployment's fact, and a domain
   page saying "this rests on a flag one engine calls experimental" states
   a rule derived from a vendor. The warning belongs to whatever speaks to
   that engine, so it stays here until a real adapter exists to carry it,
   and moves into that adapter's own docstring when one does.
5. **The `items` gap is lower priority** than assumed. The
   `conventions.md` contradiction is still just wrong and still cheap.

## When to delete this

When the real adapter lands. Keep `documents.json`: it is captured output
from a real engine and makes a good fixture for testing the real adapter
without depending on bluesky in CI.
