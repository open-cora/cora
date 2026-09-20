# TomoScan adapter spike

**This is not production code and nothing in `apps/api` or `apps/reporter`
depends on it.** Read [FINDINGS.md](FINDINGS.md) first; the findings are
the deliverable and the scripts are only how they were obtained.

## Why it exists

The reporter works and reports runs from a live engine. It has seen one
engine, and everything below its translator was written to be
engine-neutral on the strength of an argument rather than a second case.
One engine cannot tell you whether an abstraction is general or merely
well named.

TomoScan is the second engine. It is what 2-BM-S runs, it is EPICS rather
than a document stream, and it is unlike Bluesky in every dimension the
reporter has an opinion about. If AROC's run model is going to be wrong,
this is the cheapest way to find out, and finding out now matters because
the conducting direction would double the number of things that depend on
`Run`.

Three questions went in:

1. Does AROC's `Verb` set cover what this engine's runs do?
2. Does `(name, document)` fit an engine with no documents?
3. Is there anything a plan map could key on?

The answers are no, no and no, and section 7 of the findings says which
of those are the adapter's problem and which are the domain's.

## What is real and what is not

There is no beamline here and no EPICS installation. `ioc.py` serves the
lifecycle PVs with caproto, which speaks Channel Access from Python, and
pyEpics connects to it the way it connects to a real IOC.

Against that, `observe.py` runs TomoScan's own `fly_scan`, `begin_scan`,
`end_scan`, `abort_scan` and `pv_callback`, imported from the installed
package and not overridden. Those are the methods that write every status
a client can see, so the transitions recorded are produced by TomoScan's
lines rather than by an imitation of them.

The three `collect_*` methods are stubs, because the real ones drive a
camera and a rotation stage over minutes. Their stubs poll
`scan_is_running` and raise `ScanAbortError` exactly as the real
`wait_camera_done` does, which is the line that notices an abort. `__init__`
is replaced because the real one connects to roughly a hundred detector
PVs and reads a camera manufacturer to decide which of them exist.

What that leaves untested is stated at the end of the findings.

## Which TomoScan

`github.com/tomography/tomoscan`, the APS one. There is an unrelated
package called `tomoscan` on PyPI, from ESRF, for reading tomography data.
Installing the wrong one is easy and it is not the one any beamline scans
with.

## Why it lives outside `apps/`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane.
Those are all invoked with explicit paths inside `apps/api` and
`apps/reporter`, so a directory at the repo root is invisible to them.
That is deliberate, and the same reasoning as the sibling spikes: code
that has to satisfy the architecture fitness suite is a landing, and the
value of a spike is being able to write it fast and throw it away.

The dependencies are pulled in per invocation rather than added to any
`pyproject.toml`, so there is no dependency, no lockfile churn and no CI
lane touched.

## Running it

```sh
uv run --with caproto --with pyepics --with pymsgbox \
    --with "tomoscan @ git+https://github.com/tomography/tomoscan" \
    python spikes/tomoscan_adapter/observe.py
```

It starts the soft IOC itself, drives five scenarios, prints them, and
writes `transitions.json`. Takes about fifteen seconds and needs no
network beyond the first install.

A line about `broadcast_beacon_loop` failing to reach `255.255.255.255` is
caproto announcing itself on a machine that will not broadcast. Harmless,
and unrelated to anything measured.

## The files

```
   ioc.py             the lifecycle PVs, typed as tomoScan.template declares
   observe.py         the real lifecycle, five scenarios, one recorder
   transitions.json   what a monitoring client saw, all 66 of them
   FINDINGS.md        the point
```

## When to delete it

When the model questions in section 7 of the findings are answered, which
is the only reason it exists. Keep `transitions.json` if a tomography
reporter is ever written: it is what the lifecycle actually emits, and it
makes a fixture that needs neither EPICS nor a beamline.
