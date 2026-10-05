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

The core is here and tested, and so is every adapter, though not equally.
There are four over three seams, and the two filling `Running` are an
either-or a deployment settles.

| Adapter | Seam | How far it has been taken |
| --- | --- | --- |
| `epics_control` | `Adjusting` | Moves and verifies single records, checked against a soft IOC rather than a stand-in. Beamline deployments run this. |
| `tomoscan_engine` | `Running` | Hands a routine to a scan server and follows it through that server's own records. Beamline deployments run this, and scans have been driven through it. |
| `bluesky_engine` | `Running` | Runs a named measurement and reads both of a run's names back out of what the engine published, checked against a stand-in. No scan has been started through it, so every behaviour that stand-in imitates is a claim about a real engine rather than an observation of one. |
| `http_tasking` | `Tasking` and `Reporting` | Asks for work and reports each step over HTTP, checked through a transport that inspects the request rather than sending it. Beamline deployments run this. |

No seam here is unfilled. What is thin is the checking behind one of the two
engine adapters, and what is absent is anything driving real hardware: every
scan so far has gone to a simulator serving records the deployment supplies
itself.

Two gaps are worth knowing before running one unattended. **Nothing bounds how
long a run may take**: the Channel Access adapter has three clocks and the
engine adapter has none, so a scan that hangs hangs the walk. And **there is no
logging**: `Broke` keeps one line of text and no traceback, and `except
Exception` files a typo in an adapter under the same word as a motor that would
not move.

Every design decision below answers a specific way real hardware fails, and
the tests name the one each answers.

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
