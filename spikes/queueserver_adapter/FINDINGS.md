# Queueserver findings

Measured against `bluesky-queueserver` 0.0.25 and `bluesky` 1.15.1, with a
real RE Manager, a real Redis and two ordinary ZMQ clients. Numbers below
are from `findings.json`, which `probe.py` wrote.

The headline is that the question this spike inherited was the wrong one.
It was carried forward as "queueserver only serves the identity question".
Queueserver answers the identity question well, and in the same breath
reopens the device-claim question that `spikes/conductor/` closed.

## 1. The submit-time handle exists, and no reporter can ever see it

`queue_item_add` returns the item with an `item_uid` assigned, before
anything runs. That is the handle a bare RunEngine does not offer.

```
   item_uid at submit      0d52376f-a02b-41f6-afd4-23c5fc65899d
   run uid                 c5748d53-2f24-472a-a13c-e09ec37780df
   item_uid is a run uid   False
   item_uid anywhere in the start document   False
```

The last line is the one that decides something. The item uid is
queueserver's own name for a queue entry and it is not published to
anything reading documents. `apps/reporter` records runs from the
document stream, so a run filed by the reporter can never be found by an
item uid. Whatever else the item uid is good for, it cannot be the join.

This is the same shape as the constraint that settled the bare-RunEngine
half in commit e246acf, arrived at from the other direction: the join has
to be a name both clients can see, and the document stream is the only
place they both look.

## 2. A run is nameable 0.4 seconds in, not only at the end

`re_runs` with `option="open"` returns runs while the plan is still
running.

```
   run uid visible while open        c5748d53-...
   seconds until it became visible   0.41
   run uids in history afterwards    ["c5748d53-..."]
```

This is the one real gain over a bare RunEngine, where `RE(plan)` returns
uids only when the plan finishes. The identity a conductor wants is
available almost immediately, from a read, and it is the run uid rather
than a private handle. A conductor under queueserver can name its run
while the run is happening, which is what the bare-engine path gave up.

## 3. Two clients, one device, and nothing objects

Two separate ZMQ clients each added an item moving the same `motor`, one
to 1.0 and one to 9.0. Both were accepted and both ran.

```
   conductor's add succeeded          True
   other client's add succeeded       True
   what the other client was told     ""      (empty: no message at all)
   items executed                     2
   exit statuses                      ["completed", "completed"]
   users recorded                     ["aroc-conductor", "somebody-else"]
```

There is no conflict detection of any kind. The queue records who
submitted what and executes both. This is not a defect in queueserver,
which never claimed to know what a plan touches, and it is the same
finding `spikes/conductor/` reached about a bare engine. What is new is
where it leaves the conductor: `Ledger` is in-process and single
threaded, so a claim held for a conducted step is invisible to every
other client of the same queue. Under queueserver a per-device claim
protects a walk from itself and from nothing else.

## 4. The lock is coarse, cooperative, and names its holder

Queueserver's own answer is the `lock` API, and it works:

```
   lock succeeded                         True
   other client blocked                   True
   other client given the key succeeded   True
   reads still work while locked          True
   lock_info names the holder             aroc-conductor
```

The refusal the other client received, verbatim:

```
Failed to add an item: Invalid lock key:
RE Manager is locked by aroc-conductor at 09/22/2026 09:15:14
Environment is locked: False
Queue is locked:       True
Emergency lock key:    not set
Note: a walk is in progress
```

Three properties matter for a conductor. It is whole-queue or
whole-environment and never per-device, so it is coarser than a `Claim`
by a wide margin. The package's own documentation says it "is not
intended for access control", and the key being shareable is how that is
meant: a scientist locks the manager before entering the hutch and hands
the key to whoever should still be able to drive. And the refusal carries
the holder and a free-text note, which is structurally what
`Refused(step, holder, overlap)` already carries.

So the two mechanisms are not rivals at the same granularity. A lock is a
statement that one client owns the instrument for a while; a claim is a
statement about one device for one step. A conductor under queueserver
plausibly wants both, and nothing has established what the lock's
lifetime should be: per walk, per step, or per session.

## 5. Nothing runs synchronously, including the API that looks like it does

`queue_item_execute` runs an item immediately without queueing it, which
reads like the synchronous escape hatch. It is not.

```
   the call returned after      0.01 s
   manager state right after    "starting_queue"
   the plan finished after      2.48 s
```

The call returns at once and the plan runs for two and a half seconds
afterwards. There is no blocking submit anywhere in the API.

`conduct` currently holds each claim "for exactly as long as the step
runs" and gets that for free, because `acquire` blocks. Against
queueserver it does not: the conductor would have to poll `status` and
`re_runs` to know when its step ended, and the claim would be held across
a polling loop rather than across a call. That is a change to the walk,
not to an adapter, and it is the largest thing this spike found.

## 6. Two vocabularies for how one run ended, and they disagree

The same run, read two ways:

```
   history result.exit_status        "completed"
   stop document exit_status         "success"
```

Queueserver's plan-level statuses are `completed`, `failed`, `stopped`,
`aborted`, `halted` and `unknown`. Bluesky's run-level ones are `success`,
`abort` and `fail`. Six against three, describing different things: one is
how the plan ended, the other how a run ended, and one plan may hold
several runs.

A conductor reading history and a reporter reading the stop document
would therefore report different words for the same run, and
`apps/reporter`'s `ENDING_BY_EXIT_STATUS` maps only the three. Nobody has
written the other table.

One of the six is worth noting on its own. `unknown` means "the exit
status information is lost, e.g. due to restart of RE Manager", which is
the fourth terminal `spikes/tomoscan_adapter/` asked for, meaning "ended,
outcome unknown". It exists here natively, with a stated cause.

## 7. The directive id survives, under a filter somebody else configures

The metadata a conducted item carries reached the start document intact:

```
   directive in the start document   directive-1
```

So the mechanism commit e246acf shipped works through a queue as well as
through a bare engine. The caveat is in the manager's configuration dump,
which reports `permitted_re_metadata_keys: ['/']`. The documentation says
the metadata dictionary "will be filtered based on the list of permitted
metadata keys defined in the manager configuration", and the default
above let everything through.

A facility that narrows that list drops `aroc_directive_id` silently, and
the conductor would have no way to know except that the value did not
come back. `ReferenceNotCarriedError` is exactly that check, and this is
the deployment that can trigger it without anybody making a mistake.

## What this recommends

**Keep the join as it is.** The engine's run uid is still the only name
both clients can see, and queueserver publishes it faster rather than
differently. Commit e246acf does not need revisiting.

**Do not build a queueserver adapter behind the current `Acquisition`.**
The Protocol's `acquire` returns `Acquired`, which is a synchronous
answer, and section 5 says there is no synchronous submit. An adapter
that polled inside `acquire` would work and would hide the fact that the
walk no longer owns the timeline.

**The open question is not an adapter, it is whether a conducted step
owns its instrument.** Sections 3 and 4 together say the conductor cannot
enforce anything against a shared queue and that queueserver offers a
coarser tool that names its holder. Whether a walk takes the lock, for
how long, and what a `Refused` means when the refusal came from the queue
rather than the ledger, are the decisions to make before code.

**A second exit-status table is needed before anything reads history.**
Section 6, and it belongs next to `ENDING_BY_EXIT_STATUS` in
`apps/reporter/src/reporter/translate.py` rather than in the conductor,
because the reporter is what turns an engine's word into AROC's verb.

## What this spike did not do

It used `ophyd.sim` devices, so nothing here says what a real motor does
when two queue items move it. `spikes/conductor/` answered that for a
bare engine and there is no reason to expect the hardware to behave
differently because the caller changed.

It ran one RE Manager with one worker environment. A facility running
several managers, or the HTTP server in front of the ZMQ API, is a
different topology and this says nothing about either.

It did not test the lock across a manager restart, though the
documentation states the lock survives one.

It did not measure what happens when the queue is running in `loop` mode,
or when an item is added while the queue is already executing, which is
the normal case at a busy beamline and the one where a conductor's
ordering assumptions are most likely to be wrong.

It granted every plan to every user group. Whether a conductor should run
as its own user group, and what that buys, is untested.
