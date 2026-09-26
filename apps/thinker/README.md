# Thinker

*Metis, goddess of wise counsel*

Reads what an execution was asked to do and what became of it, and advises
what to run next.

**Invoked, not autonomous.** A thinker is started with an execution id in
hand, reads it once, concludes once, and exits. Nothing dispatches work to
one, because nothing in this tree reacts to an event by writing another one.
That is a fact about the system rather than a stage this package is at, and
[What is missing](#what-is-missing) says what would have to exist first.

**Reads both halves of the case, and joins them by id.** A procedure says
what the steps were and an execution says what became of them, and they pair
on the key the keeper's own routes name: an execution step's
`procedure_step_id` against a procedure step's `step_id`. Both lists arrive
in the procedure's order today, so joining by position would pass every test
here and mis-pair every step after the first insertion.

**Concludes one of four things, and writes down the one that has a record.**
`Propose`, `Stop`, `Abstain` and `Refer` are four classes, not four values of
a verdict field, because a field can be set wrong and a class cannot. Only
`Propose` becomes a record, through the keeper's `POST /proposals`, under the
thinker's own credential.

**The core names no outside system.** `case`, `conclusions`, `seams` and
`think` import the standard library and each other, and nothing else, so
forming a conclusion needs no HTTP library and no provider installed. There
is one adapter, and it is named once, at the entrypoint that picks it. That
is enforced by `tests/test_the_core_names_no_seam.py` rather than promised
here.

**Nothing in the keeper changed to make this work.** Two routes it already
had are read and one it already had is written. That is the strongest
available statement that the seam between advising and recording was in the
right place before anything needed it.

## What it is, and what it is not

A client of the keeper, not a part of it, the same way the conductor and the
reporter are. Nothing here imports `keeper` and nothing in the keeper imports
this; its own project and its own lockfile make that the interpreter's rule
rather than a convention.

It is not an agent framework. It holds no provider, no prompt and no model
name. `Inference` is one verb with no configuration, and what sits behind it
is something a deployment writes and names in a file.

It is not a scheduler. It proposes, and something else decides whether to
compose a procedure from the proposal and dispatch it. A facility that
automatically runs whatever is proposed has turned a suggestion into an
instruction, and it has done so outside this repository.

It cannot steer. Every call goes out and none comes in, so a conclusion
reached while an execution is still walking has nowhere to arrive. No command
in the keeper touches a running execution and the conductor's verbs are all
outbound.

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

The write is last and covers one arm, which is the right way round: a
conclusion nobody heard costs a re-run, and a proposal nobody concluded costs
a beamline's time.

## Four conclusions, and why only one is written

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

The three that cannot be stored go to whoever asked, printed as JSON. That is
sound precisely because a thinker is invoked: somebody is standing there. It
stops being sound the day a thinker picks its own work, because then an
`Abstain` reaches nobody and becomes indistinguishable from a thinker that was
never asked. That is a change to the keeper, not to this package.

## Two things it deliberately will not claim

**That a conclusion is any good.** There is no confidence, no score and no
self-evaluation, and there will not be one. A thinker rating its own answer
produces exactly the artefact the conductor refuses at its acquisition seam,
where an engine's own word for how a run went was taken for a finding about
the run: every corrupted scan in that project's findings came back reporting
success. A number a thinker assigns itself reads as measurement and is
assertion.

**That a failure is an abstention.** Nothing is caught. A keeper that cannot
be reached and a provider that raised both stop the thinking, and neither
becomes a conclusion. Returning `Abstain` on a failure would read as a thinker
that looked and found nothing, and would be a thinker that did not look. It is
the same call the conductor makes in the other direction, refusing to report
`Broken` for a step no seam ran.

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
python -m thinker --config thinker.toml --execution <id> --objective "..."
```

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
| A record that a thinker was asked | The keeper. `Abstain` and a thinker that was never invoked are the same silence, which is tolerable only while every thinking has a caller waiting. It becomes load-bearing the day a thinker selects its own work, and the place to hold it is an aggregate in the keeper's Counsel context rather than anything here. |
| A reason on a proposal | The keeper, and an argument. The proposal record carries a plan and parameters and no reason, so what a proposal was for lives only in what this printed. The field would have to exist there first, and a record that reads as an explanation and is a generated sentence is worse than no field. |
| A thinker tried against a running keeper | A sitting with one. Every route this reads and writes is checked against a transport that asserts on the request, which is not the same as having watched a proposal land. |
| Any logging at all | A decision about where it goes. A failure ends the run with a traceback and a status, which is honest for something a person invoked and thin for anything that runs unattended. |
| More than one execution at a time | Something asking. One invocation reads one execution. A caller wanting several runs the command several times, and whether a case should ever span them is a question nobody has asked. |
| A second reading seam | A stream the keeper is not the record of. There is none, so a second Protocol today would be one interface with one implementation reading the same API as the first. |

## The four

| Repo | Does |
| --- | --- |
| [keeper](https://github.com/open-cora/keeper) | Records what was proposed, run and produced |
| [conductor](https://github.com/open-cora/conductor) | Conducts a procedure across a beamline, one step at a time |
| [reporter](https://github.com/open-cora/reporter) | Reports what an acquisition engine did |
| [thinker](https://github.com/open-cora/thinker) | Proposes what to run next |

## Where the code is developed

**This repository is what you deploy, install and cite.** It is one deployable,
versioned and released on its own, and it runs standalone: its own lockfile,
its own suite, its own site.

**Development happens in [open-cora/cora](https://github.com/open-cora/cora)**,
a tree holding the four side by side, from which each is extracted with
`git subtree` and its history intact. What is missing here is the other
projects, and the end-to-end tests that need more than one of them at once.

A change merged here would be overwritten by the next publish, so open an issue
or fork. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
