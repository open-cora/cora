# Client contract

*How AROC's peer clients name the same run, and what that name is not.*

AROC has two clients that are not part of it. `apps/reporter` watches an acquisition engine and records what it sees. `apps/conductor` composes a procedure and drives a beamline through it, holding a device claim for each step. Neither imports `aroc`, nothing in `apps/api` imports either, and they do not import each other.

They nevertheless talk about the same runs, so they need one answer to "which run is that". This page is that answer. It is prose rather than a shared package on purpose: a third project existing to hold a string and four HTTP rules would cost more than the duplication it saves.

## A run has two names

An engine mints its own identifier for every run it opens and puts it in the start document it publishes. A conductor mints its own before it submits anything, because there is no handle at submit time: `RE(plan)` returns uids only when the plan is finished. Metadata passed at the call arrives in the start document unchanged, which `spikes/conductor/FINDINGS.md` section 7 measured against a real engine.

So a conducted run carries both:

| | minted by | known at | where it appears |
| --- | --- | --- | --- |
| run uid | the engine | the moment the run opens | `start["uid"]` |
| directive id | the conductor | before the plan is submitted | `start["aroc_directive_id"]` |

## The engine's uid is the join

The reporter files a run into AROC under the engine's uid, as the value of an `Identifier` whose scheme is configuration. A conductor that wants to find its run asks AROC for that same pair.

The directive id is not the join, and the reason is worth knowing before anyone proposes changing it. `Session._run_id_for` in the reporter resolves an engine uid to an AROC run id, and after a restart it does so by filtering `GET /runs` on the external reference. Engine documents only ever carry the uid, so a run filed under anything else is a run a restarted reporter cannot find. A `Run` holds one `external_ref`, so "filed under the conductor's name" and "findable by the engine's uid" cannot both be true today.

What the directive id is for instead: it puts the conductor's name on the engine's own permanent record, where a person reading a data catalogue can match a run to the walk that caused it. `conductor.adapters.bluesky_acquisition` reads it back out of the start document rather than echoing the argument it was given, which is what lets `conduct` refuse a walk whose engine dropped it.

## Two settings that have to agree

The scheme is a word, and two deployments have to pick the same one.

- The reporter reads `aroc.external_ref_scheme` from its TOML configuration and sends it with every run. `spikes/bluesky_adapter/FINDINGS.md` recommends `bluesky-run-uid`.
- A conductor looking a run up must be configured with that same word.

Nothing checks this. Two deployments configured differently produce a lookup that returns an empty page, which reads exactly like a run that was never recorded. It is the first thing to suspect when a conducted run cannot be found.

## What this page does not promise

**The note is writable by anyone who can start a plan.** The engine is outside AROC, so `aroc_directive_id` can be set by hand, copied between runs, or left off. That adds no exposure that was not already there: `plan_name` and `exit_status` are equally forgeable, and every run the reporter files is something AROC was told rather than something it checked. `apps/api/src/aroc/execution/aggregates/run/state.py` makes the structural point, that a reported run has no way to describe itself as a conducted one, because that distinction is not a field.

**The reference is a correlation hint, not a credential.** Nothing is granted, billed or gated on it. A wrong one costs a wrong lookup. The day something authorizes off an external reference, this design has to change before that ships.

**External references are not unique.** AROC does not enforce uniqueness across streams, and says so in `run/state.py` along with what closing it would cost. A duplicate therefore surfaces as two rows from one query rather than as a refusal, and a caller that cares should compare the page length. A conductor can tell its own run from a collision by the plan it asked for and the time it asked.

**The conductor does not call AROC yet.** It holds the join key: `Acquired.engine_reference` reaches a caller through `Done`. Making the request is a further step with its own dependency and its own configuration, and it is not built.

## When a client does start calling AROC

The reporter has already settled the four questions any AROC client meets. A second client should answer them the same way rather than differently.

| question | the answer | where the reporter keeps it |
| --- | --- | --- |
| how is a repeated send made safe | derive an idempotency key from the thing itself | `client.idempotency_key_for` |
| what does a 409 mean | usually that the work is already done, not an error | `outcomes.Unchanged` |
| which refusals are worth retrying | 5xx and 429; everything else will fail identically | `session.is_worth_retrying` |
| when to raise instead of report | raise means "ask me again", an outcome means "finished with" | `outcomes` module docstring |
