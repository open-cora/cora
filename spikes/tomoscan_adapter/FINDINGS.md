# Findings

What driving the real TomoScan lifecycle over real Channel Access actually
showed. Everything below is printed by `observe.py` or read out of the
installed package, and the two are marked apart wherever it matters. Where
the docstrings and the wire disagree, the wire wins and the disagreement
is noted.

Run against TomoScan at `github.com/tomography/tomoscan` (the APS one, not
the ESRF package of the same name on PyPI), caproto 1.3.0, pyepics,
Python 3.13. TomoScan publishes no version anyone could cite, so the
commit is the version: `b8264fe`.

The package moved under this spike, and the sections below are what a
second run against `b8264fe` says rather than what the first run said. Two
of the findings changed and one of the changes is ours. **2-BM now mints a
run identity**, which section 3 was written to say it did not, and a
failing `end_scan` now reaches the wire, which section 1 half predicted. A
third correction owes nothing to upstream: sections 4 and 6 were wrong when
they were written, and how they were wrong is stated where they are.

This spike exists to ask one question: **is AROC's run model general, or is
it Bluesky's model with general-sounding names?** One engine cannot tell
you. TomoScan is the second, it is what 2-BM-S runs, and it is unlike
Bluesky in every dimension that matters.

## The short version

**AROC's three endings are finer than what this engine emits.** Four
different endings produce one status string, on the wire, every time. A
completed scan, a camera timeout and a file overwrite abort are not
distinguishable by any client. That is the exact inverse of the Bluesky
result, where our terminals were "exactly as fine-grained as the source".

**One ending, and only one, now says it went wrong.** If `end_scan` itself
raises, a handler added since this spike first ran puts `'Scan cleanup
failed'`. It is the first outcome this engine has ever put on the wire, and
it is durable, for the unlovely reason that the line which would overwrite
it is the line that failed. It tells the four apart from none of each other.

**The one ending that is visible is visible through a request, and the
request is sticky.** `AbortScan` still reads 1 during the next scan, so the
only abort signal this engine has lies about the run after it.

**Three of the reporter's five verbs still have almost no source.** `fail`
has exactly one, the cleanup failure above, and none for the four endings
anybody will actually hit. `pause` and `resume` have none at 2-BM, though
section 6 corrects an overreach: 32-ID has a pause record, so the pair is
station-authored rather than absent from tomography.

**2-BM has a run identity now, and TomoScan still does not.** A `ScanUUID`
record was added to the 2-BM and 19-BM templates, and to no shared one. It
is minted at the start of a scan, not the end, which is the half that
matters: six scans here produced six distinct ids, each published before
the first frame. What has not changed is that it is a station's answer and
not the engine's, and that nothing clears it, so between scans the record
holds the last scan's id.

**There is still no plan.** No name, nothing that says which routine was
run. `ScanType` remains the only thing in the engine that says what kind of
act a scan was.

**Nothing is a document.** The shape is `(pv, value, timestamp)`, which is
not `(name, document)` and never will be.

And the good news, which is real: **almost everything in the reporter
below the translator is engine-neutral and survives unchanged.** The
layering was right. The seam is one layer off.

## 1. Four endings, one status

This is the finding. `fly_scan` in the installed package:

```python
except ScanAbortError:
    log.error('Scan aborted')
except CameraTimeoutError:
    log.error('Camera timeout')
except FileOverwriteError:
    log.error('File overwrite aborted')
finally:
    try:
        self.end_scan()
    except:
        ...
```

Those three branches are untouched since the first run of this spike; what
the `finally` grew is section 1.1's subject and changes nothing here.

Every branch goes to `end_scan`, and `end_scan` puts one string:

```python
self.epics_pvs['ScanStatus'].put('Scan complete')
self.epics_pvs['StartScan'].put(0)
```

**The outcome exists only in a Python log line.** Not in a PV, not in a
record, not anywhere a client can reach. `observe.py` drives all four
paths through that code and watches with a real monitor:

```
   scenario         last ScanStatus         AbortScan
   completes        'Scan complete'         0
   camera_timeout   'Scan complete'         0
   file_overwrite   'Scan complete'         0
   operator_abort   'Scan complete'         1
   after_an_abort   'Scan complete'         1
   cleanup_fails    'Scan cleanup failed'   0

   6 endings, 2 distinct final status
```

The last row is new and section 1.1 is about it. The four above it are the
finding, and they are unchanged: one string, every time.

**This is not the 2-BM subclass being unusual.** `tomoscan_2bm.py`
overrides `end_scan`, does its beamline work, and finishes with
`super().end_scan()`. It adds two status strings of its own on the way
past, `'fdt file transfer complete'` and `'scp file transfer complete'`,
and neither says how the scan ended either.

**What this costs AROC.** A reporter has three choices and all of them are
bad. Record every run `Completed`, which puts a false terminal in an
append-only log. Record nothing, which leaves runs `Running` forever.
Or AROC grows a terminal meaning "it ended and nobody can say how".

Worth saying plainly: the cheap fix is upstream, and it half works. One
`ScanStatus.put` per except branch is three lines, and `end_scan` then
overwrites it with `'Scan complete'` microseconds later, because the
`finally` runs after the branch. Tested on this rig: a subscriber does
receive both values, back to back, so the outcome reaches anything that
was listening.

What it does not do is make the outcome readable. `ScanStatus` still holds
`'Scan complete'` a moment later, so a reporter that restarts, or polls,
or asks afterwards, sees a successful scan. The outcome would be
at-most-once, delivered only to whoever happened to be subscribed, which
is the same shape as the reporter's own durability gap and worth
recognising as such.

A durable fix needs a record `end_scan` does not clobber, which is a new
PV rather than three lines. This is not a thing to work around downstream.

**The issue is open upstream and was open before this spike ran.**
`tomography/tomoscan` 181, filed 2026-08-15, states the same defect from
the source and proposes two fixes, both of which move the success put out
of `end_scan` so the handlers are not overwritten. It has no replies. What
this spike adds to it is the measurement rather than the reading, and two
things it does not contain: that the naive form of its Option A does reach
a live subscriber but not a poller, and that `_end_scan_after_failure`
landed afterwards and is a working precedent for a durable outcome inside
the package.

## 1.1 The one outcome that does reach the wire, and why it is durable

Since this spike first ran, `fly_scan`'s `finally` stopped calling
`end_scan` bare and started catching it:

```python
finally:
    try:
        self.end_scan()
    except:
        log.error('end_scan() raised an exception; running last-resort teardown instead')
        traceback.print_exc(file=sys.stdout)
        self._end_scan_after_failure()
```

`_end_scan_after_failure` puts `'Scan cleanup failed'` and `StartScan` 0.
The `cleanup_fails` scenario drives it, and a subscriber sees the scan stop
at that string and stay there.

**It is the only status in this engine that survives being read late**, and
the reason is worth stating because it is not a design: `'Scan complete'`
is durable-but-wrong for the other four because `end_scan` always reaches
it, and `'Scan cleanup failed'` is durable-and-right because `end_scan`
did not. Nothing clobbers it because the clobbering line is the one that
threw. That is the fix section 1 asked for, arrived at sideways, for one
failure mode out of six.

**It also takes the file name away.** `end_scan` publishes `FullFileName`
after the status, so a scan that fails in cleanup never publishes one at
all, and the record still holds the previous scan's. Measured: of the six
scenarios, `cleanup_fails` is the only one that published no `FullFileName`.
For any station without a `ScanUUID`, that is the single failure this
engine reports and the single scan it cannot name.

The guard and the 2-BM cleanup it protects came from this tree, as
`tomography/tomoscan` pull requests 187 and 188. Worth saying because it
means the change is not independent evidence about what upstream will do.

## 2. `AbortScan` is a request, and it is sticky

Of the four endings that collapse, the only one a client can tell apart is
an abort, and it is visible because `AbortScan` goes to 1. That PV is a
`bo` record: a button, not a result.

**Nothing in TomoScan ever puts it back to 0.** Read out of the installed
package, and then demonstrated: the scenario `after_an_abort` runs a scan
that completes normally, immediately after an aborted one, without
clearing the PV first.

```
   operator_abort   'Scan complete'    AbortScan 1
   after_an_abort   'Scan complete'    AbortScan 1   <- this one completed
```

A reporter reading `AbortScan` at the end of a scan records an abort on a
run that did not abort. The signal is not merely coarse, it is wrong, and
it stays wrong until somebody clears it by hand.

Re-checked against `b8264fe`: nothing in the package writes 0 to it, and
the scenario still completes with the PV reading 1.

**Unlike section 1, this one is not filed upstream.** Searched the issue
tracker for `AbortScan`, sticky, reset and clear: 181 covers the status, 182
the restart timestamps, 183 the enum overrides, and none of them is this. It
is the only defect in this document with no issue behind it.

There is a second-order consequence this spike did not test, because it
would need a real IOC rather than caproto: if `AbortScan` is already 1,
a second abort is a put of an unchanged value, and TomoScan's own callback
fires on monitor events. Whether a real `bo` record posts one is EPICS
behaviour this rig cannot settle. Flagged, not claimed.

## 3. 2-BM mints a run identity, and TomoScan still does not

**This section said the opposite and the package changed under it.** A
`ScanUUID` record was added on 2026-09-24, and what follows is the second
reading.

Bluesky mints a UUID4 per run and puts it in the start document. 2-BM now
does the same thing, two lines into `TomoScan2BM.begin_scan`:

```python
super().begin_scan()

# Create a new UUID for this scan
self.epics_pvs['ScanUUID'].put(str(uuid.uuid4()), wait=True)
```

**It is minted at the start, which is the half that matters.** The old
answer, the output file path, is written by `end_scan` and so cannot name
a run while the run is happening. This can. Six scans here, six distinct
ids, each on the wire before the first frame:

```
   scenario         ScanUUID before                        ScanUUID after
   completes        Unknown                                0762b176-...-1071ac9e2cfb
   camera_timeout   0762b176-...-1071ac9e2cfb              3d06c851-...-61c71030e628
   file_overwrite   3d06c851-...-61c71030e628              779df5a7-...-4f367cbf2f74
   operator_abort   779df5a7-...-4f367cbf2f74              530d1f2f-...-ba8e77a8f831
   after_an_abort   530d1f2f-...-ba8e77a8f831              9567d08f-...-02ba84ed7653
   cleanup_fails    9567d08f-...-02ba84ed7653              e3873bab-...-1991fff172dc

   6 scans, 6 distinct id, 0 read their own before starting
```

Four things a reporter has to know about it.

**It is a station's record, not the engine's.** It is declared in
`tomoScan_2BM.template` and `tomoScan_19BM.template`, and 7-BM had it
first. The base `tomoScan.template` has no such record, so every other
station still has nothing, and a tomography reporter cannot assume the PV
is there. The heading of this section is the finding: an identity exists
where somebody added one.

**It is sticky, the same shape as `AbortScan`.** The record is a
`stringout` with `PINI=YES` and it is listed for autosave, so it survives
an IOC restart and nothing ever clears it. The right-hand column above is
the left-hand column of the next row: between scans, `ScanUUID` reads the
last scan's id. Reading it is only meaningful while `StartScan` is 1, and
a reporter that reads it at any other moment gets a real, well-formed,
wrong answer. That is a milder version of the `AbortScan` problem, because
`begin_scan` at least overwrites it, and it is the same mistake.

**It lands after the scan has already been announced.** The put comes
after `super().begin_scan()`, which is the call that puts `'Beginning
scan'`. The recorded order is the same in all six:

```
   StartScan      1
   ScanStatus     'Beginning scan'
   ScanUUID       '0762b176-0896-4229-a953-1071ac9e2cfb'
   ScanStatus     'Moving rotation axis to start'
```

So there is a window in which a subscriber has been told a scan started and
still reads the previous scan's id. It is short and it is on the wrong side
of the announcement, so a reporter should take the id from the `ScanUUID`
monitor rather than reading it when `StartScan` goes to 1.

**It fits, with three characters to spare.** An EPICS string field is
`MAX_STRING_SIZE`, 40, and `str(uuid.uuid4())` is 36. Anything that
prefixed the id, with a beamline or an instrument, would truncate it
silently.

The id also reaches the data. A companion change to `dxfile` captures the
PV as an NDAttribute and writes it into the HDF5 file at
`/process/acquisition/scan_UUID`, so a file can be joined back to the scan
that made it. That is read from the commit message and not measured here.

### The file path, which is still what the other stations have

`FullFileName`, written by `end_scan` from the file plugin. The `scheme`
half of AROC's `Identifier` exists for exactly this, and
`("tomoscan-file", "/local/data/sample_042.h5")` is a usable external
reference.

Three costs, one of them new. It is only unique while the file plugin's
`AutoIncrement` is on, which is an operator setting rather than a
guarantee, where Bluesky's uid cannot be switched off. It is only known at
the **end** of a scan. And per section 1.1 it is not written at all when
`end_scan` fails, while the record keeps the previous scan's value, so the
one run this engine reports as broken is the one the file path names
wrongly.

This rig does not simulate auto-increment, so the repeated file name in
its output is an artifact of the soft IOC and not evidence of anything.

The two other id-shaped records, `ProposalNumber` and `ESAFNumber`,
identify the **experiment**, not the scan. Every scan in a week of beamtime
carries the same pair.

## 4. There is no plan

`report_run` takes a `plan_name` and the reporter maps it to a plan id.
There is nothing to map.

TomoScan has no named routine. What varies between scans is about forty
PVs, plus `ScanType`, an enum. `config.py` has sections for `general`,
`tomoscan`, `in-situ`, `vertical`, `horizontal`, `energy` and `file`, and
no concept anywhere that names a procedure.

**This section said `ScanType` had five values and it has never had five.**
The base `tomoScan.template` declares eight: `Single`, `Vertical`,
`Horizontal`, `Mosaic`, `Scan File`, `Energy`, `Energy File`, `Helical`.
2-BM overrides the record with six of its own, `Scan File` renamed to
`File` and the last two dropped. Both counts were what they are today when
this spike first ran, checked against the tree as it stood then, so this is
a miscount and not a change. It does not move the finding, which is that a
five-valued or an eight-valued enum is not a plan either way, but it is the
kind of error that makes a reporter's enum mapping wrong on two values.

It is worse than a miscount, and `tomography/tomoscan` 183 is why. A
beamline template is merged onto the base rather than replacing it, and the
merge can add a state but cannot remove one. So 2-BM's six-state override
does not take effect: the IOC runs with eight, and a client sees two states
2-BM's own file tried to delete. A reporter keying on `ScanType` must read
the union, not the station's template.

So the plan map is not merely unpopulated, it has nothing to key on. The
two honest readings:

- **`ScanType` is the plan.** One plan per value, authored by an operator,
  and the value set is per station. Coarse, but it is the only thing in the
  engine that says what kind of act this was.
- **The plan is the whole configuration.** Which makes every scan its own
  plan, and the concept stops earning anything.

The first is what a reporter should do. It is worth noticing what it
implies: the Bluesky finding that "an adapter cannot honestly author a
Plan" was about not being able to derive a schema. Here the adapter cannot
even derive a name.

## 5. Nothing is a document

`Session.handle(name, document)` and `Delivery = tuple[str, dict]` are
Bluesky's shape. A monitor callback delivers this:

```
   ('2bmb:TomoScan:ScanStatus', 'Collecting projections', 1789905947.788288)
     pv name                     value                     timestamp
```

One field, not a record. No grouping, no run, nothing that says which scan
it belongs to: correlation is "whatever scan was running when this
arrived", and the engine does not say when that changed except through the
`StartScan` busy record.

**This is the concrete design change the spike buys.** `Session` should
take an `Intent`, not a document. Today it translates and then acts:

```
   today      handle(name, document) -> translate -> act
   wanted     translate (per engine) -> act(intent)
```

The two halves are already separate inside `session.py`; what couples it to
Bluesky is the signature. Move the translator out to the caller and
`Session`, `ArocClient`, `Relay`, `outcomes` and `config` are engine-neutral
by construction rather than by luck.

## 6. Pause has no source at 2-BM, and this section overreached

What holds: there is no pause PV at 2-BM. No record for it in
`tomoScan.template` or `tomoScan_2BM.template`, and no method for it in the
base class. A tomography fly scan is a rotation stage moving at a computed
speed, and stopping it in the middle is an abort.

**What does not hold is the conclusion drawn from it.** 32-ID has a
`Pause` record, a `bo`, in `tomoScan_32ID.template`, and its
`collect_projections` reads it, puts `'Pause'` into `ScanStatus` and waits
in a loop until the operator clears it. That has been upstream since
2025-12-17, nine months before this spike, so the section did not miss a
change: it searched two templates, found nothing, and wrote a sentence
about tomography.

So `pause` does have a source, in one tomography station out of the set,
and `resume` is that operator clearing the same record rather than a
second signal. The honest reading is narrower than the one this section
reached and still uncomfortable for the verb pair: two engines in, pause is
optional, station-authored and spelled differently in each, where Bluesky's
is a property of the engine.

It remains true that a reporter pointed at 2-BM has no pause to report, and
that is the deployment that matters here.

## 7. What this says about AROC's model

The layers, measured:

```
   replaced per engine    translate.py                       230 lines
                          decode + from_subscription, most
                          of sources.py                      173 lines

   survives unchanged     client.py   config.py   relay.py
                          outcomes.py                        637 lines

   survives, with a       session.py    its handle() signature
   named change           intents.py    Verb, in 3 of its 5 values
                                        ReportRun.plan_name
                                                             278 lines
```

`__main__.py` and `__init__.py` are the remaining 280 lines and are wiring
either way.

**The good news is not a consolation prize.** The reporter was built with
one engine in front of it and a claim that everything below the translator
was general. A second engine says most of that claim held, and names the
exceptions precisely. That is what the spike was for.

**The bad news is in the domain, not the adapter.** AROC's terminal set
assumes the engine knows how its run ended. Bluesky does. TomoScan does
not, and a status set that cannot express "ended, outcome unknown" makes
"how many runs failed last week" a question AROC will answer confidently
and wrongly for every tomography beamline.

The new terminal in section 1.1 does not relieve this and slightly sharpens
it. `'Scan cleanup failed'` gives AROC one tomography failure it could map
onto `Failed` honestly, which means a reporter now has to hold both: one
ending it can name, and four it must not pretend to. A model with three
terminals and no fourth has to put those four somewhere, and every
available choice is a lie about five scans in six.

That is a decision for Execution rather than for a reporter, and it is the
kind of thing worth deciding before the conducting direction doubles the
number of things that depend on `Run`.

## 8. Personal data is sitting in the PV set

Not on the question list. `tomoScan_2BM.template` declares `UserName`,
`UserLastName`, `UserBadge`, `UserEmail`, `UserInstitution`,
`UserInfoUpdate`, `ProposalNumber`, `ProposalTitle`, `ESAFNumber` and,
added since this spike first ran, `ESAFDOINumber`. The set grew rather than
shrank, which is the direction to expect.

The Bluesky spike found one free-text field, `reason`, and declined to
store it on the grounds that free text from an engine is where personal
data ends up. Here it is not a risk, it is a schema. Any reporter reading
this PV set is one careless `parameters` mapping away from putting a named
person's badge number into an append-only log.

`apps/keeper/docs/reference/conventions.md` has the rule. This is the first engine
where following it takes deliberate effort rather than none.

## What this spike did not do

It did not run a scan at 2-BM-S, and it did not run one against a real
EPICS IOC. `collect_dark_fields`, `collect_flat_fields` and
`collect_projections` are stubs, `__init__` is replaced, and
`close_shutter` raises on demand so that section 1.1 has a failure to
catch, all for the reasons `observe.py` states.

**It did not run `TomoScan2BM`.** That class cannot be imported on Python
3.13 at all: it imports `telnetlib`, which the standard library dropped in
3.13. So the two lines that mint the id in section 3 are quoted into the
stub rather than driven, and what is measured there is the ordering and the
stickiness rather than 2-BM's own call. Running the real one is possible on
Python 3.12 and costs about forty-five more PVs in the soft IOC, most of
them the Aerotech PSO set, plus opencv, h5py and pyserial. That was
considered and not done.

What that leaves untested: anything about timing, anything about the
detector, the `bo` record semantics flagged in section 2, and whether
`ScanUUID` really survives an IOC restart, which is an autosave claim this
rig has no autosave to check. What it does not leave untested is every
claim above about the lifecycle, because `fly_scan`, `begin_scan`,
`end_scan`, `abort_scan`, `pv_callback` and `_end_scan_after_failure` are
the installed package's own, running over real Channel Access.

## When to delete this

When the model questions in section 7 are answered, which is the only
reason it exists. Keep `transitions.json` if a tomography reporter is ever
written: it is what the lifecycle actually emits, and it makes a fixture
that needs neither EPICS nor a beamline.
