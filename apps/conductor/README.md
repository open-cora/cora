# Conductor

*One boat in the chamber, and never both gates at once.*

**The conductor is the part that actually does things.** It asks what work has
been approved for its beamline, takes one job, runs it step by step through
whatever hardware and run software the site has installed, and reports
each step as it finishes. If it dies halfway, the steps that finished are still
on the record.

**It stops two jobs from driving the same device.** Before a step runs, it takes
a hold on the equipment that step names. A step whose equipment something else is
already holding is refused rather than queued: a caller told which job holds the
device can go and do something else, and a queue would only make it wait.

**It runs at the beamline** rather than in a data centre, because the protocols
that talk to motors work only on the local network. Everything it needs from the
record it asks for over HTTP, and nothing ever calls in.

## It does not depend on any one engine

The same program covers three situations, and the only difference between them is
what it hands a measurement to.

```
   no engine               it drives the hardware itself
   an engine               it hands the step over and keeps track of the run
   a managed queue         it is one client among several
```

This is the point of the design rather than a side effect. A facility that has
adopted no particular run software can still run approved work, because
driving hardware directly needs no engine at all. Tying what the system can do to
one engine would put a choice of software in front of the science.

It never owns an engine either. Where one exists the site hands it over and
nothing here imports one, which is what lets those three rows be three settings
rather than three programs.

**The core knows nothing about the outside.** `claims`, `procedure`, `seams`,
`conduct` and `outcomes` import the standard library and each other and nothing
else, so putting a job together needs no beamline software installed. Every
adapter lives under `conductor/adapters/` and is named once, at the point that
picks it. `tests/test_the_core_names_no_seam.py` enforces that, rather than this
paragraph promising it.

## What it will not claim

**That it is an engine.** It does not run the inner loop of a scan,
it does not know what a measurement does, and it does not judge whether the
science worked. It asks an engine for a measurement and keeps two things straight
around it: which step holds which device, and which run belongs to which step.

**That a step worked.** `Done` means the call returned without an error. Every
corrupted scan in the findings below came back reporting `exit_status:
"success"`, so a word here meaning "it did what it meant to" would be exactly the
overclaim that produces confident wrong data. What the engine said is passed on
word for word and something further out decides.

**That killing it stops anything.** A driver was killed mid-move and the motor
carried on to its target with nothing alive asking for it, and no stop message
was ever sent. A hard kill offers no hook to hang cleanup on. So the list of
holds is not durable, and anything that must stop when abandoned needs a watchdog
next to the hardware, which is not this. What a killed job leaves behind is its
record, which is narrower and is what the reporting step is for.

## Where it stands today

The core is here and tested, and so are the three edges, though not equally.
`conductor.adapters.epics_control` moves and verifies single records, checked
against a soft IOC rather than a stand-in.
`conductor.adapters.bluesky_engine` runs a named measurement and reads both
of a run's names back out of what the engine published, checked against a
stand-in: no scan has been started from this package, only from a spike, which is
where every behaviour that stand-in imitates was measured.
`conductor.adapters.keeper_http` asks for work and reports each step over HTTP,
checked through a transport that inspects the request rather than sending it. See
[What is missing](#what-is-missing).

Every design decision below came from a spike, and the tests name the finding
each one answers.

## Reading further

The detail that used to sit here lives on the site, where the nav carries it and
a broken cross-link fails the build.

| To read about | Page |
| --- | --- |
| Running one, configuring it, stopping it | [Running one](docs/running.md) |
| The pieces, the hold, the control adapter | [Architecture](docs/architecture.md) |
| What a walk records and where | [Conducting](docs/conducting.md) |
| What travels between this and the keeper | [Contract](docs/client-contract.md) |
| The words, used the same way in code and prose | [Glossary](docs/glossary.md) |

In short: `uv sync --all-extras` then `uv run pytest -q`. The suite starts a
caproto soft IOC and talks to it over a real Channel Access socket, so it takes
about ninety seconds and needs no beamline.

## What is missing

| Piece | Waiting on |
| --- | --- |
| A run adapter driven against a real engine | A sitting with one. `bluesky_engine` is written and checked against a double built from what a spike measured, which is not the same as having run it. |
| A queueserver adapter | A decision. A bare RunEngine hands a caller nothing at submit time, so the uid that joins arrives only when the plan finishes; queueserver assigns an item uid up front, which would let a conducted run be named before it exists. That is a different and probably better answer, and it needs Redis and a second sitting. |
| A bound on how long a run may take | An adapter to bound. `Control` has three clocks and `Engine` has none, so a scan that hangs hangs the walk. The right timeout is a property of the engine rather than of this Protocol, which is the argument for settling it with the first adapter rather than before it. |
| Any logging at all | A decision about where it goes. `Broke` keeps one line of text and no traceback, which is thin for something that will run unattended for hours, and `except Exception` files a typo in an adapter under the same word as a motor that would not move. |
| A control seam that is not EPICS | Something asking. Tango is the obvious second, and the Protocol has two verbs, so the cost is the adapter rather than the design. |
| A conductor tried against a running keeper | A sitting with both. Every piece of the path has tests and the seams between them have doubles on one side or the other, which is not the same as having watched a dispatch reach a motor. |
| A conducted scan watched end to end | A sitting with a beamline. The two ids now reach a start document and the reporter reads exactly those keys, with both sides pinning the spelling, but no run has gone out of one and into the other. |
| More than one execution at a time | Something asking. `take` asks for one and a walk is sequential, so a beamline with two procedures that share no hardware runs them one after the other. The ledger is already the mechanism if that changes. |
| Parallel steps | Nothing has asked. The ledger is already the mechanism: two steps may run at once exactly when their claims do not overlap. |
| A Procedure aggregate in the keeper | Deliberate. Three of four corrupted runs in the findings arrive as Completed, so an enactment record would say every step finished, which is true and useless. This package is what will say what such a record should hold. |

## Related projects

Published from the same development tree, and separate deployables on purpose.
Nothing here imports any of them and none of them imports this; the boundary is
the interpreter's rule rather than a convention.

| Project | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Holds the record, and who may add to it |
| [reporter](https://github.com/open-cora/reporter) | Reports what happened, and where the data went |
| [thinker](https://github.com/open-cora/thinker) | Suggests what to run next |

## Where the code is developed

**This repository is what you deploy, install and cite.** It is one deployable,
versioned and released on its own, and it runs standalone: its own lockfile,
its own suite, its own site.

**Development happens in [open-cora/cora](https://github.com/open-cora/cora)**,
a tree holding this project and the three above side by side, from which each is extracted with
`git subtree` and its history intact. What is missing here is the other
projects, and the end-to-end tests that need more than one of them at once.

A change merged here would be overwritten by the next publish, so open an issue
or fork. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
