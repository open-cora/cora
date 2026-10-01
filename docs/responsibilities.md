# Which client records what

*Two clients wrote to one step of an execution, and two of the facts they
wrote were written by both. This page sets out the axis that tells the two
jobs apart, names the overlaps it found, and records their removal from the
conductor. The code is changed; nothing is deployed.*

## Three ways of splitting them, and the one that holds

**By tense.** The driver says a step started, the watcher says it ended. This
breaks the engine's state machine.
`apps/keeper/src/keeper/execution/features/report_step_run/decider.py`
accepts `Started` only from nothing, and every ending only from `Running` or
`Paused`, so splitting that machine across two processes makes each one
necessary to the other. A beamline with no watcher leaves every run at
`Running` forever, and an ending arriving without its start is refused.
Disagreement, which is two fields today, becomes a conflict on one.

**By observer.** This is what the model says now.
`apps/keeper/docs/bounded-contexts/execution.md` holds the two accounts
apart because "neither observer is reliable and collapsing the two would
make this system pick a winner between claims it cannot check." That is
sound for the three driver outcomes an engine never sees, and it is weaker
than it reads for the one that matters, because on the terminal word the two
clients read the same thing:

```
               conductor reads                reporter reads
  ────────────────────────────────────────────────────────────────────
  bluesky      exit_status, off the stop      exit_status, off the stop
               document, collected in         document, off the socket
               process
  tomoscan     the ScanStatus record          the ScanStatus record
```

Same document, same record. They cannot disagree about it except by one of
them not arriving, so the independence the section rests on is not there for
the case it describes.

**By what driving is required to know.** The axis that survives:

> Could this fact be known without having driven?
> No, and it is a fact about the control flow, which is the conductor's.
> Yes, and it is an observation, which is the reporter's.

It is testable one fact at a time, which neither of the others is, and it
makes each client's absence meaningful rather than corrupting. A record with
no watcher then says what was attempted and nothing about what happened,
which is honest, instead of saying a step finished and filing data for it.

## The facts, sorted by that question

```
  fact                             knowable without     belongs    written
                                   having driven?       to         by today
  ──────────────────────────────────────────────────────────────────────────
  claimed this execution           no                   conductor  conductor
  step Refused, a claim clash      no                   conductor  conductor
  step Skipped                     no                   conductor  conductor
  step Broken, the seam raised     no                   conductor  conductor
  step Done, the call returned     no                   conductor  conductor
  the walk ended                   no                   conductor  conductor
  ──────────────────────────────────────────────────────────────────────────
  Started, Completed, Aborted      yes                  reporter   reporter
  engine_reference                 yes                  reporter   was both
  the dataset address              yes                  reporter   was both
```

Six of nine were already where the axis puts them. The two at the bottom are
the subject of this page, and neither of them is the step report, which is
the conductor's own account and belongs to it.

## The first overlap: engine_reference

Both clients wrote it. The conductor sends it on a `Done` from
`apps/conductor/src/conductor/adapters/http_tasking.py`, and the keeper
records it there. The reporter sends it on a `Started`, and the keeper
records it there too, which
`apps/keeper/src/keeper/execution/features/report_step/decider.py` and its
sibling slice both allow.

It is an engine's own name for a run, lifted out of a start document or a
record. Nothing about having driven is required to read it, so by the axis
it is the reporter's.

The cost of the overlap was small and real: two writers of one field, no
rule saying which wins, and no reader able to tell which one wrote what it
is looking at. **The conductor no longer sends it.** The keeper still
accepts it on the driver's report, and that is deliberate rather than
unfinished: the log already holds `ExecutionStepDone` events carrying the
field, so the command cannot be narrowed behind them.

## The second overlap: the dataset address, which was a live double write

`apps/conductor/src/conductor/seams.py` gives the conductor a `Filing` seam,
and argues for it this way: an engine answering with a location has already
given the address, while an engine answering with a name needs a store to
resolve it, and only a reporter holds the store. So a conductor files where
its engine returns a location, which
`apps/conductor/src/conductor/adapters/tomoscan_engine.py` does and
`apps/conductor/src/conductor/adapters/bluesky_engine.py` does not.

**The premise is false for the engine it was written for.**
`apps/reporter/src/reporter/adapters/tomoscan_records.py` does not resolve
anything. It polls the same IOC, reads the same `FullFileName`, and yields a
second delivery that becomes a dataset registration directly. No store is
asked, because there is none to ask.

```
                    ┌──────────────────────┐
                    │  TomoScan IOC        │
                    │  FullFileName        │
                    └───────┬──────────┬───┘
                      reads │          │ polls
                            ▼          ▼
                    ┌───────────┐  ┌───────────┐
                    │ conductor │  │ reporter  │
                    │  Filing   │  │  Filing   │
                    └─────┬─────┘  └─────┬─────┘
                          └───────┬──────┘
                                  ▼
                        one address, one step,
                        registered twice
```

At a beamline running both, each registered the same address against the
same step. It worked, and only because both sides were built to absorb it:
each `Filing` docstring said filing one address twice against one step was
expected rather than exceptional, and the keeper makes the second write
return the first record's id.

That is a system tolerating a duplication rather than a system that does not
have one. **The conductor's half is gone.**

## What removing both cost

The conductor shed `Filing`, `Address`, `reference_scheme`, `_file`,
`Unfiled`, `HttpFiling`, `dataset_key_for`, the startup wiring that chose a
filing seam from the engine, and the `engine_reference` arm of its step
report. It kept `Tasking`, `Adjusting`, `Running` and `Reporting`, and it
kept the engine's own reference and word on `Ran`, read inside a walk,
returned to whoever embedded it, and sent nowhere.

Two tests went with the behaviour they covered. One in the conductor's suite
existed only to check that every engine declared a reference scheme. One in
this tier compared the conductor's copy of the dataset idempotency key
builder against the reporter's, and would have been left comparing one. Both
are named in the commit that removed them, which is where a deleted file's
name belongs: a citation here would point at nothing and this tier has a
check that says so.

**The second deletion carries a condition, and it is the one most likely to
be lost.** That test was the only thing anywhere comparing the conductor's
spelling of the dataset retry key against the reporter's, and it said so in
its own docstring. Deleting it is correct exactly as long as the conductor
registers no datasets. If filing returns to the conductor in any shape, that
comparison has to return with it in the same change. Two clients writing two
spellings of one key into one table is not caught by either project's suite,
because each stops at its own directory, and nothing would go red.

## What green means after this, which is less than before

The conductor's suite passes 245 of 245 with the port to itself. That number
is worth reading beside the one it replaced rather than alone.

```
  test functions at HEAD      242        collected cases      276
  test functions after        217        collected cases      245
  removed                      25        cases removed         31
  added                         0
```

The difference between 25 and 31 is parametrised cases expanding. Nothing
there is wrong: removing a capability should remove the tests that held it,
and leaving them behind would have been the defect. But a guard and the
behaviour it guarded come off in the same change, so green afterwards is a
weaker statement than green before, and it is weaker by a measured amount
rather than an unknown one. Anyone quoting the 245 should quote the 443
deleted test lines beside it.

The code was the smaller half, as expected. Roughly twenty files argued that
the conductor filed datasets, including a titled section in `seams.py`, and
all of it had to become an argument for why it does not. The argument that
replaced it is in `apps/conductor/src/conductor/seams.py`, under the heading
naming the seam that is not there, because an absence nobody argued for is
an absence somebody re-adds.

## What it changes about a deployment, and the order that matters

It inverts the question of whether a reporter is needed at a beamline whose
engine answers with a location.

A conductor there used to cover the step outcome and the dataset, so a
reporter looked like a second opinion. It now covers the step outcome only,
and a beamline with no reporter has a record of what was attempted and no
record of what happened. That is coherent rather than partial: nobody was
watching, and the record says so.

**Which makes this a sequencing requirement and not just a refactor.** A
beamline recording datasets through its conductor today stops recording them
the moment this reaches it, and starts again when a reporter is running
there. The reporter has to go first. A conductor shipped ahead of one leaves
a gap in Custody for every scan in between, and the gap is invisible from
the beamline: the walk still reports, the steps still read `Done`, and only
the dataset is missing.

**And the view built to find that gap goes blind at the same moment.**
`apps/keeper/src/keeper/execution/adapters/postgres_step_summary_lookup.py`
fixes its filter at `engine_reference IS NOT NULL AND dataset_id IS NULL`,
and says in its own prose that a row reaches the result "only by carrying an
engine reference". Both halves of that pair now come from the reporter. With
one running, the question is cleaner than it was, because it stops joining a
driver's claim against a watcher's and asks one client about its own
account. With none running, the listing is not empty because there are no
gaps, it is empty because nothing can put a row in it, and the two read
identically from outside.

That is the strongest form of the ordering argument. Until a reporter runs,
removing the conductor's `engine_reference` costs the facility its only
means of noticing the very gap the rest of this change creates.

It also removes the reason to give the driver's vocabulary a word for an
engine that did not finish. That idea exists only because the conductor
currently files a dataset for an aborted scan and reports `Done` for it. A
conductor that files nothing has no such claim to correct.

## What is not decided here

**Whether the keeper should stop accepting `engine_reference` on the driver's
report.** Leaving it accepted costs nothing and keeps the command surface
open to a driver that is not this conductor. Removing it is the honest
version of the axis. It is a second mirror either way.

**Whether the reporter grows the legs it is named for.**
`apps/keeper/docs/reference/glossary.md` defines a reporter as whatever tells
this system what it saw elsewhere: an engine's account of a run, a device's
faults, a pursuit's charges. The keeper has a command for each and only the
first has a client anywhere. If the reporter becomes the only thing recording
what happened at a beamline, whether it also reports faults decides whether
it is that beamline's observer or one engine's tap.

**Two pages that still give the old reason for running no reporter.**
[Where each part runs](beamlines/index.md) and [7-BM](beamlines/7-bm.md) both
say a reporter cannot run at these beamlines because TomoScan publishes no
documents. A reporter that reads records rather than documents has existed
since the TomoScan source landed, and those two pages have not caught up.
