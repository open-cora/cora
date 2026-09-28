# Findings

What driving a real engine into a real store, and the result into the real
HTTP surface, actually showed. Everything below is printed by the two
scripts in this directory. Where the store's documentation and the wire
disagree, the wire wins and the disagreement is noted.

Run against tiled 0.2.18, bluesky 1.15.1, ophyd 1.11.2, Python 3.13.

## The short version

The **natural key is settled, and it is not a string the store hands you**.
One node reports two different addresses depending on how the handle was
obtained, so the key is computed rather than read, and the computation is
part of the key's definition.

The **timing question turned out not to be a timing question**. Whether a
reporter finds a complete node at `stop` is decided by subscription order,
in process, deterministically. That replaces a retry loop with one line of
wiring, and the guarantee is lost the moment the reporter is remote.

Three things the spike surfaced that were not on the question list. **The
store carries the engine's start and stop documents verbatim**, which means
the Custody leg needs no second source for a timestamp and could in
principle be driven without the document stream at all. **There is no
file for a record to point at**, which kills the third candidate key for a
better reason than "it did not work". And **an adapter does not need the
store's client library**: the same key comes off the raw HTTP surface, byte
for byte.

Two more were added after the rest, in sections 9 and 10. **The store does
emit**: one webhook event per run carries everything a Custody record needs,
so a receiver would make no store call at all. **But a webhook cannot reach
a host that cannot be dialled**, and the store's WebSocket can, which is the
route to prefer wherever that is true. The facility that wrote the store
drives its own catalog from the document stream and treats the store as the
sink, which is the split this reporter already has.

## 1. The natural key: settled, and the defect is upstream of the choice

Three candidates went in: the node's path inside the store, its full URI,
and the file the bytes live in. The third is gone (section 4). The first
two both fail in the same way, for the same reason, and the reason is the
finding.

**The same node reports two addresses depending on how you reached it.**
A handle obtained from `create_container` carries a leading empty ancestor
segment; a handle obtained from a search or a lookup does not.

```
  root:
    created  uri  http://.../api/v1/metadata//at_the_root
    searched uri  http://.../api/v1/metadata/at_the_root
    created  path '/at_the_root'     searched path 'at_the_root'
  nested:
    created  uri  http://.../api/v1/metadata//nested/child
    searched uri  http://.../api/v1/metadata/nested/child
    created  path '/nested/child'    searched path 'nested/child'
```

It is not a root-only quirk, which was the first reading and was wrong: the
nested case splits identically. It is about the handle, not the node.

That matters because an external reference is a value object. Two spellings
are two values, and two values are two Custody records for one body of
data. `resolve.py` runs all three candidates through the real `Identifier`
and says so plainly:

```
    keyed on raw uri          2 RECORDS
    keyed on raw path         2 RECORDS
    keyed on normalised path  one record
```

**Recommendation:** `scheme = "tiled-node-path"`, `value` = the node's
ancestors and key joined by `/` **with empty segments dropped**. For a run
the writer produced, that is `raw/<run uid>`, 40 characters against the
200-character bound, and the deepest leaf in the tree reaches 104.

The normalisation is not tidying and must not be written twice. This is the
rule in [patterns.md](../../apps/keeper/docs/reference/patterns.md#cross-stream-uniqueness)
that says a derivation key must byte-match the read-side expression, in a
variant that rule does not currently cover: here the two parties that
disagree are both *producers* of the key, and neither is the read side.

**The store's client is not needed to compute it.** The client's
`node.item` is the `data` member of the store's own HTTP response, so the
same two fields are readable with an ordinary GET and no dependency. The
probe reads both ways and compares:

```
  completes         200  key=raw/<uid>  same_as_client=True  missing_run=404
  plan_raises       200  key=raw/<uid>  same_as_client=True  missing_run=404
  abort_from_pause  200  key=raw/<uid>  same_as_client=True  missing_run=404
  stop_from_pause   200  key=raw/<uid>  same_as_client=True  missing_run=404

  envelope    ['data', 'error', 'links', 'meta']
  data        ['attributes', 'id', 'links', 'meta']
  attributes  ['access_blob', 'ancestors', 'data_sources', 'metadata',
               'sorting', 'specs', 'structure', 'structure_family']
```

Four for four, and a run the store does not hold answers `404` rather than
an empty `200`, which matters more than it looks: "there is no data for
this run" is the reporter's most consequential answer and an adapter that
guessed the shape of it would report a missing node as a present one.

This is what settles the dependency question rather than arguing it. A
reporter already holds an HTTP client for AROC, so reading the store the
same way is symmetric, and the one thing a client library would buy here
is insulation from an envelope that two fields are being read out of.

**Why the path rather than the URI**, given normalisation fixes both. The
URI embeds the server's address, so a store that moves rewrites every
record that cites it, and the scheme half already exists to say which
vocabulary the value belongs to. A deployment serving two stores runs two
reporters with two schemes, which is the same trade the reporter already
makes for the plan map. The cost is that a Custody record is not resolvable
by someone who was not told which store to ask, and that is the right cost:
AROC is not the store's directory.

## 2. The race is not a race, it is subscription order

All three things were armed and watched: the writer, a reporter looking at
the store, and the document stream driving both.

```
  writer first
    at start  present, start=True stop=False children=[]
    at stop   present, start=True stop=True  children=['primary']
  reporter first
    at start  NOT THERE (KeyError)
    at stop   present, start=True stop=False children=['primary']
```

Both callbacks run on the engine's thread in the order they were
subscribed. So a reporter subscribed **after** the writer sees a complete
node at `stop`, every time, with no retry and no sleep. A reporter
subscribed before it sees a node with the ending not yet written, every
time, also deterministically.

This is much better news than the question expected, and it changes the
answer to "do you control the writer". You do not need to wrap it. You need
to be subscribed after it, which is satisfiable even when the writer is
somebody else's.

**The cost has to be stated plainly.** That ordering guarantee exists only
because both callbacks are in one process. An adapter subscribing to a
remote engine over a message bus has no such guarantee, and for that shape
the question really is a race and wants a bounded retry or a writer-side
report. This is the same trade the sibling spike found between `state_hook`
and the document stream: in-process buys you more and reaches less.

**Registering at `start` is not available.** The node does not exist yet
when the reporter is second, and when it is first the node exists but
carries no ending and no children. Either way the record would have to be
amended later, which a single-event aggregate cannot do.

## 3. The store carries the engine's own timestamps, exactly

Not on the question list, and it removes a whole category of worry. The run
node's metadata holds the `start` and `stop` documents in full, including
their `time` fields, and the values match the engine's to the last digit:

```
  completes          engine stop=1789915675.86416   store stop=1789915675.86416
  plan_raises        engine stop=1789915677.6911628 store stop=1789915677.6911628
  abort_from_pause   engine stop=1789915679.475926  store stop=1789915679.475926
  stop_from_pause    engine stop=1789915681.2796218 store stop=1789915681.2796218
```

`exit_status` comes through the same way. So a Custody record takes its
`occurred_at` from the store's copy of the ending rather than from the
clock or from a second subscription, which is what section 6 of the sibling
spike spent its argument earning for runs.

The larger consequence is worth naming even though nothing acts on it yet:
**the Custody leg has no hard dependency on the document stream.** A
reporter that only ever walked the store could register datasets with
honest timestamps. Whether it could also carry the Execution leg is
untested and doubtful, because nothing here observed how a pause reaches
the store, if it does at all.

## 4. There is no file to point at, and that is the store working

The third candidate key was the asset's own `data_uri`, the one address
that would survive the store being torn down. It is not available for a run
the writer produced:

```
  writer  raw/<uid>                         data_sources=None
  writer  raw/<uid>/primary                 data_sources=None
  writer  raw/<uid>/primary/internal/det    data_sources=None
  client  /written_directly                 assets=['file://localhost/.../written_directly']
```

An array the client writes directly lands as a file and says where. The
writer's readings are rows in a table and have no file. This is the same
fact as the error the catalog raises if it is given file storage alone:

```
RuntimeError: The adapter <class 'tiled.adapters.sql.SQLAdapter'> supports
storage types ['EmbeddedSQLStorage', 'SQLStorage', 'RemoteSQLStorage'] but
the only available storage types are dict_values([FileStorage(...)])
```

A run's readings are tabular, so there is no file, so a Custody record
naming one would be inventing an address. Drop the candidate and do not
reach for it again when somebody asks where the data really is: the answer
is the store, and the store is the one that knows.

## 5. A search does not descend

```
  completes   from the store root: (nothing)   from the writer root: ['<uid>']
```

A search is scoped to the container it is called on and does not reach into
grandchildren. So a reporter cannot find a run by uid without already
knowing where the writer points.

That is not an obstacle, it is a confirmation: where the writer points is
deployment configuration, alongside the plan map and the external-reference
scheme the reporter already carries. It does mean a reporter cannot
discover its own scope, and a misconfigured one finds nothing and says
nothing rather than finding the wrong thing, which is the better failure.

## 6. A failed run still gets a node, and the node is empty

```
  scenario           exit_status  node?  children
  completes          success      yes    primary
  plan_raises        fail         yes    (none)
  abort_from_pause   abort        yes    (none)
  stop_from_pause    success      yes    (none)
```

Every ending produces a node. Three of the four produce one with no data
under it, because the plan ended before any reading was taken.

**Register it anyway.** "There is a node for this run and it holds nothing"
is a fact, and it is the fact somebody looking for missing data needs. A
reporter that refused to record an empty node would leave Custody silently
disagreeing with the store, and the disagreement would look exactly like
the reporter having been down.

## 7. The grants

Queries are authorized with the query name as the command name, so the read
half is a grant and not a formality.

```
grant       RegisterDataset  ListRuns  GetRun

withhold    DefinePlan  ReportRun  CompleteRun  AbortRun  FailRun
```

The withheld list is longer than the engine reporter's and the reason is
the same one, applied in the other direction. A thing that hears from the
store has no business saying a run happened or how it ended: it was not
there for either, and the store's copy of the stop document is a copy, not
a second witness.

If one process carries both legs it runs as one actor holding the union,
and the split above is then a statement about what a store-only deployment
would grant rather than about today's wiring.

## 9. The store does emit, and one event means "the run is finished"

Added after the rest, and it reverses an assumption the earlier sections
were written under. The Custody leg was designed as a lookup because a
store answers rather than announces. **This store announces.** Tiled has
webhooks, in the released version that everything above was run against:

```
  installed tiled 0.2.18
  orm tables      webhooks, webhook_deliveries
  registration    POST /api/v1/webhooks/target/{path}
  delivery        3 attempts, exponential backoff, outcome rows persisted
  authenticity    HMAC-SHA256 in X-Tiled-Signature
  deduplication   X-Tiled-Event-ID header
```

Driving a real engine through the writer with the dispatcher intercepted,
one `count` of three frames fires four events:

```
  1. container-child-created            key=<run uid>    carries start
  2. container-child-created            key='primary'
  3. container-child-created            key='internal'
  4. container-child-metadata-updated   key=<run uid>    carries start AND stop
```

**`container-child-metadata-updated` on the run node is the ending, once
per run.** The three `created` events are not: the first fires when the
node appears, which section 2 showed happens at `start` with no ending
written. A subscription with `events: null` therefore gets four
deliveries where one is wanted.

**The delivery carries everything a Custody record needs**, which is the
part that changes the design rather than confirming it:

```
  path      ['7eb00073-4608-4d83-a162-2143784e2f5b']   the node address
  key       '7eb00073-...'                             the engine's run uid
  metadata  {'start': {...}, 'stop': {...}}            including the ending time
```

So a webhook receiver makes **no call to the store at all**. The lookup in
`reporter/stores.py` exists because the document path has to go and ask;
a receiver is told. That makes the webhook path strictly simpler than the
one built, not merely faster.

### Two things stop this being free

**The lifespan gotcha, for whoever reproduces it.** `Context.from_app`
does not run the app lifespan, so `Context.startup` never builds the
dispatcher and no event fires however the catalog was configured. The
probe constructs `WebhookDispatcher` by hand. A real server does not have
this problem; a test harness does, silently.

**Tiled will not deliver to a private address.** Loopback and the private
ranges are blocked, and the `allow_delivery_hosts` escape hatch does not
take the hostname in the URL. It compares against `socket.getfqdn(ip)`,
the reverse-DNS name of the resolved address:

```
  allow_delivery_hosts=['localhost']               REFUSED
  allow_delivery_hosts=['1.0.0.127.in-addr.arpa']  ALLOWED
```

And on a network with no reverse DNS there is no value that works.
`getfqdn` returns the IP string, and the allow-list refuses an IP:

```
  ValueError: Allow delivery host 10.0.1.7 must be a valid hostname
```

**The value it demands is the value it refuses.** So whether a reporter
can receive webhooks at all comes down to one question, which is a fact
about DNS rather than about any code: does the reporter's host have a PTR
record, as seen from the host Tiled runs on? `can_tiled_reach.py` in this
directory answers it, using Tiled's own check, and has to be run there.

If the answer is no, the options are a PTR record, the egress proxy
Tiled's own error message suggests, or polling the catalog instead.
`nodes.id` is an autoincrement integer, so a sweep has a cursor.

Section 10 adds a fourth, which is better than all three and was
there before webhooks were. Read the two together.

## 8. Everything else with nowhere to go

The run node's metadata carries the whole start and stop documents, so
everything the sibling spike listed as unmapped is here too and is equally
unheld. Three things are new and specific to the store:

```
   specs           [{'name': 'BlueskyRun', 'version': '3.0'}]
   structure       the tree: primary -> internal -> seq_num, time, det, ts_det
   access_blob     {} on everything the writer wrote
```

One worth a decision rather than a shrug: **`specs`** is the store's own
typed marker saying what kind of thing a node is. A Custody record holds
nothing like it, so "which of these datasets is a run and which is a
reprocessing" is a question nothing here can answer. It is the obvious
second field if one is ever wanted, and it should not be added before
something asks.

**Not tested.** How a pause reaches the store, if it does. Whether a node
that is moved keeps its path, which is the argument for Custody holding a
later "moved" event rather than a mutable location field. Whether
`data_sources` becomes reachable with a different permission. Two stores
under one deployment.

## 10. The webhook is not the only way in, and its author says what it is for

Section 9 ends by naming three ways past the allow-list: a PTR record, an
egress proxy, or polling. There is a fourth. It is supported, it is in the
same release everything above was run against, and it predates webhooks.

### The store has a WebSocket, and it points the other way

```
  tiled 0.2.18   @router.websocket("/stream/single/{path:path}")
  auth           a first message over the socket, then accept or close 4003
```

Direction is the whole of the difference, and on a network that permits
only one of them it is the only thing that matters:

```
   webhook                          websocket
   ---------------------------      ---------------------------
   store ---POST---> receiver       receiver ---connect---> store
                                             <---events----

   the store opens it               the receiver opens it

   needs an inbound port, a         needs outbound reach and
   name that reverse-resolves,      nothing else
   and the allow-list to pass
```

A receiver behind a one-way boundary can use the second and cannot use
the first, whatever the allow-list is set to. `can_tiled_reach.py` is
still the right probe if webhooks are wanted; it is no longer the only
question to ask.

What the WebSocket costs is stated plainly by the same issue that
proposed webhooks: it is best effort. The client holds the connection,
and after a disconnect it is the client's job to ask for a replay within
limits or to re-read at rest. That is the same durability gap this
reporter already carries on its engine subscription, so it is a known
price rather than a new one.

### The webhook was designed for a receiver that is not this one

Issue #1315, which is where webhooks came from:

> Webhooks might be a better fit for use cases such as kicking off
> workflow jobs when datasets are created or closed. Here, we want a
> stronger guarantee of delivery... Webhooks do not require subscribers
> to hold active open connections to receive updates.

And the follow-up that asked for the allow-list in the first place,
issue #1380:

> Sometimes, Webhooks need to be delivered to selected internal services.

Internal services. The receiver in view is an addressable job runner in
the same deployment, not a host that cannot be dialled at all. Section 9
read the allow-list as an obstacle to a design. It is better read as a
fence around a different design, one that assumed reachability from the
start.

### The allow-list fix exists and was not merged

PR #1466, "Fix webhook allow-list to compare URL hostname instead of
reverse DNS lookup", proposes exactly the change section 9 implies: drop
`socket.getfqdn(ip_str)` and compare the parsed hostname instead. It was
closed without merging and without a single comment, and it was authored
by Copilot.

```
  webhooks.py:174 in v0.2.18      host = socket.getfqdn(ip_str)
```

So the behaviour section 9 measured is current rather than a version
artifact. Open alongside it: #1380 on making the block list configurable,
#1358 on enhancements, #1431 and #1432 on the documentation.

Read together that is a young feature nothing is leaning on yet. A
facility delivering webhooks across a real network boundary would have
hit the reverse-DNS behaviour long before we did.

### What the facility that wrote the store actually runs

Not this. The production path is the document stream, and the store sits
at the end of it rather than at the head:

```
        RunEngine
           |
           +---> Kafka              nslsii.configure_base(
           |                          publish_documents_with_kafka=True)
           |                        read from /etc/bluesky/kafka.yml
           |
           +---> TiledWriter ---> the store
```

`TiledWriter` is a bluesky callback, `bluesky/callbacks/tiled_writer.py`,
not a component of the store. Beamline startup profiles subscribe it in
process with the RunEngine; hxn, ixs, tst, hex, cdi, smi and bmm all load
it.

So the store is a sink of the document stream there, and anything that
needs to know a run finished subscribes to the stream rather than asking
the store. **That is the split this reporter already has**, arrived at
from the other direction: the engine leg for the lifecycle, the store leg
for where the data went.

### What this section is worth

Mostly a decision not to build something. Concretely:

- If a store is ever deployed here and has to notify the reporter,
  subscribe to `/stream/single/`. Do not start with a webhook receiver.
- The webhook is not wrong. It is for a deployment shape where the
  receiver is reachable by name.
- Neither is urgent while no store is deployed and the data is files on a
  filesystem, which `StoreLookup` already accommodates without a new
  Protocol.

**How this was checked, and what was not.** Public code at the v0.2.18
tag, public issues and pull requests, and public beamline startup
profiles. No running system and no private deployment configuration, so
"what the facility runs" is inferred from what its beamlines load at
startup rather than read off a deployment.

## What this changes

1. **The key is computed, not read.** `(tiled-node-path, <normalised
   path>)`, and the normalisation belongs in one function that both the
   reporter and anything reading back share. Writing it twice is the defect
   in section 1 reintroduced by hand.
2. **`register_dataset` takes `occurred_at`** from the store's copy of the
   ending. That confirms the R8 reading from the design discussion: this is
   a `register_*` that describes rather than makes, the first in the tree.
3. **The reporter subscribes after the writer**, and that sentence belongs
   in the reporter's README rather than in AROC's docs, because it is a
   fact about one deployment's wiring.
4. **No unique index on the Custody projection.** The derived idempotency
   key makes a redelivery a no-op without one, and the same argument
   Execution used applies: a duplicate that is visible beats one that is
   swallowed.

   The key is `register-dataset:<normalised path>`. This paragraph said
   the run uid first, which is the same string today because one run
   produces one dataset, and silently wrong the day one produces two:
   both registrations would carry one key, so the second would come back
   holding the first dataset's id and would never be recorded. Custody
   refused to derive a dataset's identity from its run precisely so that
   one-per-run would not be frozen into the schema, and keying the retry
   note on the run puts it back in the worse place. A schema announces
   itself with a migration; a key format does not.
5. **Registering an empty node is correct**, and the reporter should not
   grow a rule against it.
6. **The store adapter takes no new dependency.** One GET against the
   metadata route yields the same key the client yields, and a run the
   store does not hold answers 404. So the adapter is an httpx call
   behind a Protocol, and the store's client stays out of the reporter's
   lockfile.

## Refreshing this

Not deleting it. `collect.py` writes the fixture the reporter's suite
asserts against, and the claims below are cited from code that still
runs, so the directory is permanent. The spike README says why at length.

Re-run `collect.py` against a newer store and the capture is
overwritten. Ids and timestamps change every run, so the diff is mostly
noise; what to read is whether the suite still passes. The assertions are
written against the structural claims above rather than the bytes.
