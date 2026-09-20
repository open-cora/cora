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

Two things the spike surfaced that were not on the question list. **The
store carries the engine's start and stop documents verbatim**, which means
the Custody leg needs no second source for a timestamp and could in
principle be driven without the document stream at all. And **there is no
file for a record to point at**, which kills the third candidate key for a
better reason than "it did not work".

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
rule in [patterns.md](../../docs/reference/patterns.md#cross-stream-uniqueness)
that says a derivation key must byte-match the read-side expression, in a
variant that rule does not currently cover: here the two parties that
disagree are both *producers* of the key, and neither is the read side.

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
  completes          engine stop=1789875922.33628   store stop=1789875922.33628
  plan_raises        engine stop=1789875924.1462872 store stop=1789875924.1462872
  abort_from_pause   engine stop=1789875925.747366  store stop=1789875925.747366
  stop_from_pause    engine stop=1789875927.539052  store stop=1789875927.539052
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
   key `register-dataset:<run uid>` makes a redelivery a no-op without one,
   and the same argument Execution used applies: a duplicate that is
   visible beats one that is swallowed.
5. **Registering an empty node is correct**, and the reporter should not
   grow a rule against it.

## When to delete this

When the dataset leg of the reporter lands. Keep `nodes.json` and move it
to `apps/reporter/tests/` at that point, the way `documents.json` moved:
it is real output from a real store and makes a good fixture for testing
that leg without putting the store in CI.
