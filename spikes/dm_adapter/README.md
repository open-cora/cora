# Data management adapter spike

**This is not production code and nothing in `apps/api` or `apps/reporter`
depends on it.**

**Nothing here has been run yet, and there is no `FINDINGS.md`.** Every
sibling spike opens by sending you to one, because the findings are the
deliverable and the scripts are only how they were obtained. This page is
the exception and says so rather than pointing at a file that is not
there. Its siblings state their answers in the third paragraph; this one
cannot, because the questions below are open and because running it needs
something the others did not: an account at the facility. The section on
that is the most important one here, and it is why this page exists before
the scripts do.

## Why it exists

`spikes/tiled_adapter/` drove one store and Custody was written against
what it found. That store is not the one the reference beamline keeps its
data in. The instrument template a deployment would actually run carries a
data management service in its configuration, its startup and a guide of
its own, and this tree has no record of it anywhere: not a port, not a
scheme, not a sentence.

So Custody currently rests on a single case, in the same way the run model
rested on a single engine until `spikes/tomoscan_adapter/` ran and found
three of five verbs had no source. One store cannot tell you whether a
context is general or merely well named.

Four questions, and each one is load-bearing for something already
written.

1. What identifies a body of data in this service, given that the external
   reference has to carry it and cannot change afterwards? Two candidates
   are already visible in public source and both look wrong: a dataset
   name derived by truncating a run's uid to eight hex characters, and a
   record id minted by the client rather than the server.
2. When may a reporter ask? The store spike settled this in one line of
   wiring because subscription order decided it in-process. This service
   is asynchronous by construction, with a poll period and a timeout
   measured in minutes, so the same question has a different shape and
   possibly a different answer.
3. **Does the service already hold the join?** Custody says "what no store
   holds is which run produced what it is keeping", and calls that join
   "the whole of what this context adds". Public source shows this service
   being handed the engine's run uid as a field on its own dataset record.
   If that is what a deployment does, the sentence is false here.
4. Is a processing job a run, a custody event, or neither? Custody's page
   already says reprocessing is a custody event. Against that, a job has a
   submitter, a duration and an ending, which is the shape of a Run.

Question 4 carries a second one. The job's terminal states are four where
this tree's endings are three, and the extra one reads as "ran out of time
rather than finished or failed". `spikes/tomoscan_adapter/` section 7 says
a fourth terminal meaning "ended, outcome unknown" has to be decided
before conducting doubles what depends on `Run`. This may be the second
independent case that settles it.

## Why this one cannot be run the way the siblings were

Every sibling spike drives the real thing on a laptop. A soft IOC serves
Channel Access, a store runs its own server in-process, an engine needs
nothing but itself. That is what lets those findings say "the wire wins".

This service has no such mode. There is no local deployment to stand up,
and the client authenticates through environment variables that a setup
script in a beamline account defines. **So the wire is not reachable from
here, and a finding that cannot reach the wire is reading.** This project
distrusts reading on purpose.

The honest response is to split the work by what kind of evidence each
part can produce, and to mark the three apart everywhere they appear, the
way `spikes/ophyd_adapter/` marks observed behaviour apart from what it
read out of the installed package.

| Class | What it can settle | Available |
| --- | --- | --- |
| Driven against a real deployment | Anything. What a server returns, what it rejects, how long it takes. | Needs a facility account |
| Driven against a stub | What the client sends, what it requires, what it raises when a field is missing. | Here, now |
| Read out of the installed package | Constant sets, exception taxonomy, the state machine's vocabulary. | Here, now |

A stub cannot overrule documentation, because a stub is documentation that
somebody typed twice. It can still answer the half of question 1 that is
about what the client constructs rather than what the server stores, and
that half is where both suspect candidates live.

Questions 2 and 3 need class one. They are the ones to take to whoever
holds an account.

## Which package, and one trap worth writing down

The client is `aps-dm-api`, version 10.1.0 at the time of writing. It is
`noarch` and depends on `decorator` and Python, so it installs on any
platform including this one.

It is published on the facility's own conda channels and **is not on
PyPI**. The name `dm` on PyPI is an unrelated dictionary mapping library,
so `pip install dm` succeeds, imports, and is not this. Anything written
here that resolves the import without checking what it got is testing the
wrong package.

That also makes this the first spike whose dependency cannot come from
`uv run --with`. The friction is real and it is a finding of its own,
because an adapter needs the same install path in whatever runs it.

## Why it lives outside `apps/`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane.
Those are invoked with explicit paths inside `apps/api`, `apps/reporter`
and `apps/conductor`, so a directory at the repository root is invisible
to them. That is deliberate and it is the same reasoning as the sibling
spikes: code that has to satisfy the architecture fitness suite is a
landing, and the value of a spike is being able to write it fast and
throw it away.

It is also the only place allowed to name the products involved, for the
reason `test_the_domain_names_no_product.py` gives: which service a
deployment runs is a deployment's fact, and a rule stated for one reads as
a rule derived from one.

Note what that test does **not** yet have. It grew a store family when
Custody landed, and this service would be a third family. It is outside
the scanned set by construction, because the enumerators reach `src/aroc`
and `docs` and nothing else, so nothing has to change today. The day a
scheme for this service is named in a docs page is the day it does.

## What this will be

Not written yet. The shape the siblings settled on is two halves that
answer separately, and the split here is forced by the evidence table
above rather than chosen.

```
   probe.py         what the installed client requires and raises,
                      and the state machines read off its constants
   stub.py          a server that records what the client sent
   resolve.py       every candidate key through the real Identifier,
                      which is the half that needs no service at all
   FINDINGS.md      the point
```

`resolve.py` is worth writing first and costs nothing to run. The store
spike's equivalent posted no dataset: it assembled the value the slice
would be handed and put it through the value object the record inherits,
which is the part that can be wrong today and expensive to change later.
A truncated uid and a client-minted id can both be put through that
without any service being reachable, and if either fails there, question 1
is half answered before anyone opens an account.

## The operational question this does not cover

Who the caller is. The client reads its identity from environment
variables parsed out of a bash script on disk, and the station name it
finds there becomes the owner of any job it starts. `apps/reporter`'s
README already lists "an identity to run as" as an open gap and expects
the answer to be an actor in Access. This service wants a second identity,
of a different kind, that a facility issues to a workstation rather than
to a person or a process.

That is a deployment question rather than a model question, so it is
recorded here and not asked. It will matter to whoever writes the adapter.

## When to delete it

Not on the same terms as the others. `spikes/tiled_adapter/` tried to
delete itself when its adapter landed and was wrong three times over,
because its capture was a fixture the suite still asserts against and its
findings were cited from code that still runs. If this spike ever produces
a capture from a real deployment, that capture is the only copy of
something no test can regenerate, and it outlives the experiment.
