---
template: home.html
---

# Runs the work at the beamline.

The conductor is the part that actually does things. It asks what work has been approved for its beamline, takes one job, runs it step by step through whatever hardware and run software the site has installed, and reports each step as it finishes. If it dies halfway, the steps that finished are still on the record.

## Where this sits

Beamline software assumes somebody is watching. CORA is four programs for the case where nobody is, carrying the three things a person supplied by being present: the judgement about what to run next, the authority that made it permitted, and the account of what was actually done.

| | |
| --- | --- |
| [Keeper](https://github.com/open-cora/keeper) | holds the record, and who may add to it |
| **Conductor** | runs the work at the beamline |
| [Reporter](https://github.com/open-cora/reporter) | reports what happened, and where the data went |
| [Thinker](https://github.com/open-cora/thinker) | suggests what to run next |

**This is the part that runs approved work**, at the beamline, on whatever the site already has installed. [CORA](https://github.com/open-cora/cora) sets out why the four exist and how they fit.

## What it enables

**A facility that has adopted no particular run software can still run approved work.** Driving hardware directly needs no engine at all, so a choice of run software stops being a precondition.

**Two jobs cannot drive the same device.** Before a step runs it takes a hold on the equipment that step names. A step whose equipment something else is already holding is refused rather than queued: a caller told which job holds the device can go and do something else, and a queue would only make it wait.

**A crash loses the run, not the account of it.** The steps that finished are already on the record, filed as they finished rather than at the end.

## How

The same program covers three situations, and the only difference between them is what it hands a measurement to.

```
   no engine               it drives the hardware itself
   an engine               it hands the step over and keeps track of the run
   a managed queue         it is one client among several
```

This is the point of the design rather than a side effect. Tying what the system can do to one engine would put a choice of software in front of the science. It never owns an engine either: where one exists the site hands it over, which is what lets those three rows be three settings rather than three programs.

It runs at the beamline rather than in a data centre, because the protocols that talk to motors work only on the local network. Everything it needs from the record it asks for over HTTP, and nothing ever calls in.

## What it will not claim

**A conductor is a driver that takes work from the intake rather than being handed it**: it asks what it may drive at its beamline, claims one, and walks it. That is the whole of the role, and the record keeps the same word for it, so a deployment may run anything that claims and walks. What follows is what the word does not buy.

**That it is an engine.** It does not run the inner loop of a scan, it does not know what a measurement does, and it does not judge whether the science worked. It asks for a measurement and keeps two things straight around it: which step holds which device, and which run belongs to which step.

**That a step worked.** A finished step means the call returned without an error. Corrupted scans have come back reporting success, so a word here meaning "it did what it meant to" would be exactly the overclaim that produces confident wrong data. What the engine said is passed on word for word and something further out decides what it meant.

**That killing it stops anything.** A driver was killed mid-move once and the motor carried on to its target with nothing alive asking for it. Anything that must stop when abandoned needs a watchdog next to the hardware, and that is not this. What a killed job leaves behind is its record, which is narrower and is what the reporting step is for.

## Where it stands today

Both seams are written: one that drives hardware directly and one that hands a step to an engine. Every piece of the path has tests and every seam has a double on one side or the other, which is not the same as having watched a dispatch reach a motor. A conductor runs at each of the four beamlines today, each holding a connection to the record, and that is read back from the hosts rather than remembered here. What has not happened is a dispatch followed through to data.

## The pages

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | What it needs, how to configure one, and what a stop or a kill leaves behind |
| [Conducting](conducting.md) | What a job promises, what a restart does, and what survives when the program does not |
| [Architecture](architecture.md) | The pieces, one walk end to end, why the hold names records, and what a put cannot do |
| [Contract](client-contract.md) | The agreements this keeps at its edges: two names for one measurement, and the keys that join them |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |
| [Naming](naming.md), [Conventions](conventions.md), [Workflow](workflow.md) | The rules to keep when editing this code |

Every design decision here answers a specific way real hardware fails, and the tests name the one each answers. The `README.md` sets those out, along with what is not built yet and what each missing piece is waiting on.
