# Thinker

*Reads the whole chart, then looks up with one thing to say.*

**The thinker is where judgement goes.** It reads what a run was asked to do and
what became of it, puts the two side by side, hands the whole picture to whatever
does the thinking, and writes the answer down.

**You supply the brain.** There is no AI provider here, no prompt and no model
name. `Inference` is one call with no settings, and what sits behind it is
something a site writes and names in a file. What this settles is the shape of
the question and the shape of the answer: what a reader is given to think about,
and which answers it is allowed to give.

**It suggests, and never decides.** An answer goes on the record as a suggestion,
and turning a suggestion into real work is a separate act that needs permission
somebody granted. That split is built in rather than a stage to be grown out of.
A facility that runs whatever is suggested has turned advice into an order, and
it has done so outside this repository.

**It cannot interrupt.** Every call goes out and none come in, so an answer
reached while work is still running has nowhere to land. Advice goes on the
record and whatever reads next finds it there.

**It is started, not pushed to.** A thinker is handed one question, reads once,
answers once, and exits. Whether the question was put there by a person at a
terminal or by a loop that person allowed, it is picked up and answered the same
way, which is what lets one program serve a watched session and an unwatched one
without a switch.

**The core knows nothing about the outside.** `case`, `conclusions`, `seams` and
`think` import the standard library and each other and nothing else, so reaching
an answer needs no HTTP library and no AI provider installed. There is one
adapter and it is named once, at the point that picks it.
`tests/test_the_core_names_no_seam.py` enforces that, rather than this paragraph
promising it.

## What it will not claim

**That it is an agent framework.** It holds no provider, no prompt and no model
name, and it will not grow them. A model name, a temperature and a retry policy
are settings for whatever a site builds, and none of them appear here.

**That it is a scheduler.** It suggests, and something else turns a suggestion
into a job and approves it. Merging the two would put the deciding inside the
advising, where nobody could refuse it.

**That an answer is any good.** There is no confidence score and no self-rating,
and there will not be one. A thinker rating its own answer produces exactly what
this system refuses everywhere else, where a thing reporting on itself was taken
for a finding about the thing. A number a thinker gives itself looks like a
measurement and is an opinion.

**That a failure is an abstention.** Nothing is swallowed. A record it cannot
reach and a provider that crashed both stop the thinking, and neither turns into
an answer. Returning `Abstain` after a failure would read as a thinker that
looked and found nothing, when it is a thinker that did not look.

## Where it stands today

Both halves of a case are read and joined by id, and all four answers are written
down. Three of the four needed somewhere to land that did not exist at first, and
that somewhere is a record of having been asked, which a thinker picks up and
answers. The suggesting arm needed nothing new: two routes that already existed
are read, and one that already existed is written.

What has not happened is a thinking against a running deployment. Every route is
checked through a transport that inspects the request rather than sending it,
which is not the same as having watched a suggestion land.

## Why the case is the centre of this package

A case is one execution with every composed step paired against whatever
became of it, plus the objective if the caller gave one. No single keeper
record holds it, so an adapter reads the two halves and the core pairs them,
and the result is the only thing the thinking ever sees.

Either half alone is a worse question. The record says a step ended `Refused`
and cannot say what the step was for, so a reader can tell that something did
not happen and not what. The procedure is the same for every execution of it
and therefore says nothing about this one.

Three distinctions are carried through the case rather than flattened,
because the keeper draws all three and collapsing any of them would be this
package deciding something the keeper deliberately left open:

- **A missing outcome is not `Skipped`.** Absent means nothing was ever said,
  which is what a driver that died leaves behind. `Skipped` means the walk
  reached the decision and passed the step over.
- **Whether an execution ended is read off its status, never counted from its
  outcomes.** An execution can carry an outcome for every step and not be
  `Ended`, and an `Ended` one can be missing most of them.
- **An outcome reported against a step the procedure does not list is
  refused.** The two halves are then not about one execution, and no pairing
  of them is worth making. `MismatchedCaseError` names every such step rather
  than the first.

## The design in one picture

```
   the core: standard library and each other, nothing else
   ------------------------------------------------------
   case.py                 conclusions.py         seams.py
     Reading                 Propose                Keeper
       asked, became           plan_id                read
       procedure, ended        parameters             propose
     Step                      said                 Inference
       index, step_id        Stop                     conclude
       asked, became         Abstain
     Case                    Refer
       execution_id
       procedure
       steps, ended
       objective
     assemble
       Reading -> Case
       joins by id
       refuses an orphan
          \                     |                      /
           \                    |                     /
            +-----------> think.py <-----------------+
                            read, conclude, advise
                            once, then over
                                 |
                                 v
                            Thought
                              case, conclusion, proposal_id
                                 |
                                 v
                            the write happens last and for one arm,
                            so a thinker that dies partway through
                            has advised nothing

   adapters/: each one knows a single outside system
   -------------------------------------------------
   keeper_http.py     implements Keeper over the keeper's own HTTP API
                        two reads, because a case spans two records
                        keys each half on the id the other one cites
                        pairs nothing: the core does that
                        lets a refused proposal through
                        sends no idempotency key, on purpose
                        imports nothing: a client is handed over

   between the two: it composes no case and knows no system
   ----------------------------------------------------------------------
   config.py          three settings, and a profile to build an inference

   The arrow between them points one way and only at the entrypoint.
   Nothing above imports anything below, including the one in the middle.
```

There is no loop. A conductor has one because work is dispatched to it and it
has to go looking; nothing dispatches to a thinker. Adding the loop is a
smaller change than what would have to exist for the loop to have anything to
ask for.

The writes are last, so a thinker that dies part way through has advised
nothing and answered nothing, and the inquiry it held stays claimed and
unanswered rather than carrying a verdict nobody reached. On the one arm with
two writes the proposal goes first and the answer cites it, because a death
between them should leave a proposal that reads as any other actor's rather
than an inquiry naming a proposal nobody made.

## Four conclusions, and the inquiry that gave three of them somewhere to go

| | |
| --- | --- |
| `Propose` | run this next |
| `Stop` | the objective is met, and running more would be waste |
| `Abstain` | nothing here warrants a next run that this can see |
| `Refer` | a person should look at this |

`Stop` and `Abstain` are the pair most easily collapsed and the pair it costs
most to collapse. `Stop` is a finding about the objective: it is met.
`Abstain` is a finding about the thinker: it sees no next step. A facility
told the second when the first was true keeps running, and one told the first
when the second was true stops early.

A package with only the storable arm would have settled what a thinker may
conclude by never providing a way to conclude anything else, and it would have
settled it the same day somebody first needed the answer to be no.

For a while three of the four went only to whoever asked, printed as JSON,
which held precisely because a thinker is invoked and somebody was standing
there. This page said that would stop holding the day a thinker picked its own
work, because an `Abstain` would reach nobody and become indistinguishable
from a thinker that was never asked, and that closing it was a change to the
keeper rather than to this package.

The keeper has since grown an Inquiry: a record of somebody asking, which a
thinker claims and answers. So all four conclusions are written now, and an
answer carries how much of the execution was covered when it was read, because
the same conclusion means something different at two steps of six than at six
of six and nothing downstream can recover which it was.

## Running it

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
uv run pyright src tests
```

The suite needs no keeper and no provider. Both seams are exercised through
doubles, and the HTTP adapter is checked through a transport that asserts on
the request rather than sending it.

## Configuring it, and running it as a process

```sh
python -m thinker --config thinker.toml --inquiry <id>
python -m thinker --config thinker.toml --execution <id> --objective "..."
```

Two ways to name the question and one thinking either way. The first answers
one already on the record, claiming it first and exiting 3 if another thinker
holds it, which is how a question put over another surface reaches one. The
second opens a question and then answers it, which is what somebody at a
terminal with an execution in hand does.

There is no third way that leaves no record, and the absence is deliberate:
a conclusion nobody can find afterwards is the state the inquiry ended.

It reads one execution, thinks once, prints the answer as JSON and exits. It
is not a server and listens on nothing.

```toml
[keeper]
base_url = "https://keeper.example"
token = "a-thinker-token"

# Required. The dotted path names something importable that returns an
# Inference, because a client with credentials and state of its own is an
# object a file cannot hold. A model name, a temperature and a retry
# policy are arguments to whatever this builds, and appear nowhere here.
[inference]
profile = "beamline_2bm.thinking:inference"
```

There is no beamline setting. A conductor is told which one it is at because
it asks for work before it has any and the question would otherwise be
circular; a thinker is given an execution and the record says where the work
ran.

There is no objective setting either. It changes per invocation, which is what
makes it an argument. A thinker configured with a standing objective would
apply yesterday's question to today's execution without anybody having said
so.

The exit status says whether the thinker ran and never what it concluded. Any
of the four conclusions is 0, a keeper or provider failure is 1, and a
configuration that will not load is 2.

## What is missing

| Piece | Waiting on |
| --- | --- |
| A provider adapter | A decision about which provider, and a sitting with it. `Inference` is satisfied by whatever a deployment's profile builds, and nothing in this repository builds one. Until a second adapter exists, the rule that no adapter may import a sibling ranges over a single file. |
| A reason on a proposal | The keeper, and an argument. The proposal record carries a plan and parameters and no reason, so what a proposal was for lives only in what this printed. The field would have to exist there first, and a record that reads as an explanation and is a generated sentence is worse than no field. |
| A thinker tried against a running keeper | A sitting with one. Every route this reads and writes is checked against a transport that asserts on the request, which is not the same as having watched a proposal land. |
| Any logging at all | A decision about where it goes. A failure ends the run with a traceback and a status, which is honest for something a person invoked and thin for anything that runs unattended. |
| More than one execution at a time | Something asking. One invocation reads one execution. A caller wanting several runs the command several times, and whether a case should ever span them is a question nobody has asked. |
| A second reading seam | A stream the keeper is not the record of. There is none, so a second Protocol today would be one interface with one implementation reading the same API as the first. |

## Related projects

Published from the same development tree, and separate deployables on purpose.
Nothing here imports any of them and none of them imports this; the boundary is
the interpreter's rule rather than a convention.

| Project | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Holds the record, and who may add to it |
| [conductor](https://github.com/open-cora/conductor) | Runs the work at the beamline |
| [reporter](https://github.com/open-cora/reporter) | Reports what happened, and where the data went |

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
