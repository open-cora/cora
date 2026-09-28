---
template: home.html
---

# Runs the work at the beamline.

The conductor is the part that actually does things. It asks what work has been
approved for its beamline, takes one job, runs it step by step through whatever
hardware and acquisition software the site has installed, and reports each step
as it finishes. If it dies halfway, the steps that finished are still on the
record.

**It stops two jobs from driving the same device.** Before a step runs, it takes
a hold on the equipment that step names. A step whose equipment something else
is already holding is refused rather than queued: a caller told which job holds
the device can go and do something else, and a queue would only make it wait.

It runs at the beamline rather than in a data centre, because the protocols that
talk to motors work only on the local network.

## It does not depend on any one acquisition engine

The same program covers three situations, and the only difference between them
is what it hands a measurement to.

```
   no acquisition engine   it drives the hardware itself
   an engine               it hands the step over and keeps track of the run
   a managed queue         it is one client among several
```

This is the point of the design rather than a side effect. A facility that has
adopted no particular acquisition software can still run approved work, because
driving hardware directly needs no engine at all. Tying what the system can do to
one engine would put a choice of software in front of the science.

It never owns an engine either. Where one exists the site hands it over, which is
what lets those three rows be three settings rather than three programs.

## What it will not claim

**That it is an acquisition engine.** It does not run the inner loop of a scan,
it does not know what a measurement does, and it does not judge whether the
science worked. It asks for a measurement and keeps two things straight around
it: which step holds which device, and which run belongs to which step.

**That a step worked.** A finished step means the call returned without an error.
Corrupted scans have come back reporting success, so a word here meaning "it did
what it meant to" would be exactly the overclaim that produces confident wrong
data. What the engine said is passed on word for word and something further out
decides what it meant.

**That killing it stops anything.** A driver was killed mid-move once and the
motor carried on to its target with nothing alive asking for it. Anything that
must stop when abandoned needs a watchdog next to the hardware, and that is not
this. What a killed job leaves behind is its record, which is narrower and is
what the reporting step is for.

## The pages

**Running one**, if you have to install one at a beamline.

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | What it needs, how to configure one, and what a stop or a kill leaves behind |

**Understanding it**, if you want to know what it does and why.

| Page | What it answers |
| --- | --- |
| [Conducting](conducting.md) | What a job promises, what a restart does, and what survives when the program does not |
| [Architecture](architecture.md) | The pieces, one walk end to end, why the hold names records, and what a put cannot do |
| [Contract](client-contract.md) | The agreements this keeps at its edges: two names for one measurement, and the keys that join them |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |

**Changing it**, if you are editing the code.

| Page | What it answers |
| --- | --- |
| [Conventions](conventions.md) | How this project is written: naming, comments, commits, test names |

Every design decision here came from a spike that drove real hardware, and the
tests name the finding each one answers. The `README.md` is where those findings
are quoted, along with what is not built yet and what each missing piece is
waiting on.
