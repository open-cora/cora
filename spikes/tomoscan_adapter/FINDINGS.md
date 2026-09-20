# Findings

What driving the real TomoScan lifecycle over real Channel Access actually
showed. Everything below is printed by `observe.py` or read out of the
installed package, and the two are marked apart wherever it matters. Where
the docstrings and the wire disagree, the wire wins and the disagreement
is noted.

Run against TomoScan at `github.com/tomography/tomoscan` (the APS one, not
the ESRF package of the same name on PyPI), caproto 1.3.0, pyepics,
Python 3.13.

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

**The one ending that is visible is visible through a request, and the
request is sticky.** `AbortScan` still reads 1 during the next scan, so the
only abort signal this engine has lies about the run after it.

**Three of the reporter's five verbs have no source.** `fail`, `pause` and
`resume` cannot be produced from anything TomoScan publishes.

**There is no run identity and no plan.** No uid, no name, nothing that
says which routine was run. The closest thing to a key is the output file
path.

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
    self.end_scan()
```

Every branch goes to `end_scan`, and `end_scan` puts one string:

```python
self.epics_pvs['ScanStatus'].put('Scan complete')
self.epics_pvs['StartScan'].put(0)
```

**The outcome exists only in a Python log line.** Not in a PV, not in a
record, not anywhere a client can reach. `observe.py` drives all four
paths through that code and watches with a real monitor:

```
   scenario         last ScanStatus    AbortScan
   completes        'Scan complete'    0
   camera_timeout   'Scan complete'    0
   file_overwrite   'Scan complete'    0
   operator_abort   'Scan complete'    1

   5 endings, 1 distinct final status
```

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
PV rather than three lines. Whoever writes a tomography reporter should
open the issue; this is not a thing to work around downstream.

## 2. `AbortScan` is a request, and it is sticky

The only ending a client can see is an abort, and it is visible because
`AbortScan` goes to 1. That PV is a `bo` record: a button, not a result.

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

There is a second-order consequence this spike did not test, because it
would need a real IOC rather than caproto: if `AbortScan` is already 1,
a second abort is a put of an unchanged value, and TomoScan's own callback
fires on monitor events. Whether a real `bo` record posts one is EPICS
behaviour this rig cannot settle. Flagged, not claimed.

## 3. There is no run identity

Bluesky mints a UUID4 per run and puts it in the start document. Nothing
here does anything equivalent. Searched every record in `tomoScan.template`
and `tomoScan_2BM.template`: no uid, no scan id, no serial, nothing.

The two id-shaped records that do exist, `ProposalNumber` and `ESAFNumber`,
identify the **experiment**, not the scan. Every scan in a week of beamtime
carries the same pair.

**The only per-scan identifier is the output file path**, `FullFileName`,
written by `end_scan` from the file plugin. Which does work: the `scheme`
half of AROC's `Identifier` exists for exactly this, and
`("tomoscan-file", "/local/data/sample_042.h5")` is a usable external
reference.

Two costs to state. It is only unique while the file plugin's
`AutoIncrement` is on, which is an operator setting rather than a
guarantee, where Bluesky's uid cannot be switched off. And it is only
known at the **end** of a scan: `FullFileName` is written by `end_scan`,
so a reporter that wants to record a run when it starts has nothing to
name it with yet.

This rig does not simulate auto-increment, so the repeated file name in
its output is an artifact of the soft IOC and not evidence of anything.

## 4. There is no plan

`report_run` takes a `plan_name` and the reporter maps it to a plan id.
There is nothing to map.

TomoScan has no named routine. What varies between scans is about forty
PVs, plus `ScanType`, a five-valued enum: `Single`, `Vertical`,
`Horizontal`, `Mosaic`, `Scan File`. `config.py` has sections for
`general`, `tomoscan`, `in-situ`, `vertical`, `horizontal`, `energy` and
`file`, and no concept anywhere that names a procedure.

So the plan map is not merely unpopulated, it has nothing to key on. The
two honest readings:

- **`ScanType` is the plan.** Five plans, one per value, authored by an
  operator. Coarse, but it is the only thing in the engine that says what
  kind of act this was.
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

## 6. Pause and resume have no source

There is no pause PV. Not an unreliable one, not an experimental one:
there is no record for it in either template and no method for it in the
base class. A tomography fly scan is a rotation stage moving at a computed
speed, and stopping it in the middle is an abort.

For Bluesky, `pause` and `resume` rested on a flag its own authors call
removable. Here they rest on nothing. Two engines in, the pair looks less
like a property of runs and more like a property of Bluesky.

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

That is a decision for Execution rather than for a reporter, and it is the
kind of thing worth deciding before the conducting direction doubles the
number of things that depend on `Run`.

## 8. Personal data is sitting in the PV set

Not on the question list. `tomoScan_2BM.template` declares `UserName`,
`UserLastName`, `UserBadge`, `UserEmail`, `UserInstitution`,
`ProposalNumber` and `ESAFNumber`.

The Bluesky spike found one free-text field, `reason`, and declined to
store it on the grounds that free text from an engine is where personal
data ends up. Here it is not a risk, it is a schema. Any reporter reading
this PV set is one careless `parameters` mapping away from putting a named
person's badge number into an append-only log.

`docs/reference/conventions.md` has the rule. This is the first engine
where following it takes deliberate effort rather than none.

## What this spike did not do

It did not run a scan at 2-BM-S, and it did not run one against a real
EPICS IOC. `collect_dark_fields`, `collect_flat_fields` and
`collect_projections` are stubs, and `__init__` is replaced, both for the
reasons `observe.py` states.

What that leaves untested: anything about timing, anything about the
detector, and the `bo` record semantics flagged in section 2. What it does
not leave untested is every claim above about the lifecycle, because
`fly_scan`, `begin_scan`, `end_scan`, `abort_scan` and `pv_callback` are
the installed package's own, running over real Channel Access.

## When to delete this

When the model questions in section 7 are answered, which is the only
reason it exists. Keep `transitions.json` if a tomography reporter is ever
written: it is what the lifecycle actually emits, and it makes a fixture
that needs neither EPICS nor a beamline.
