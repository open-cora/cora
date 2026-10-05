# Thinker

*Reads the whole chart, then looks up with one thing to say.*

**The thinker is where judgement goes.** It reads what a run was asked to do and
what became of it, puts the two side by side, hands the whole picture to whatever
does the thinking, and writes the answer down.

**You supply the brain.** There is no AI provider here, no prompt and no model
name. `Concluding` is one call with no settings, and what sits behind it is
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

**It goes looking, and nothing pushes to it.** A thinker asks the keeper for a
question nobody has taken up, and the keeper holds that request open until there
is one. Whether the question was put by a person at a terminal or by an agent, it
is picked up and answered the same way, which is what lets one program serve a
watched session and an unwatched one without a switch.

Naming a question still works and is how a person answers one they have in hand.
What changed is that nobody has to.

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

One runs against a running deployment, holding its intake open at a live record
and asking again each time the wait expires. What has not happened there is an
answer: no inquiry has reached it, so everything past the intake is still
checked through a transport that inspects the request rather than sending it,
which is not the same as having watched a suggestion land.

## Reading further

The detail that used to sit here lives on the site, where the nav carries it and
a broken cross-link fails the build.

| To read about | Page |
| --- | --- |
| Running one, configuring it, what the exit status means | [Running one](docs/running.md) |
| What it concludes and what it refuses to claim | [Thinking](docs/thinking.md) |
| The seams, and how both are exercised without a provider | [Architecture](docs/architecture.md) |
| What travels between this and the keeper | [Contract](docs/client-contract.md) |
| The words, used the same way in code and prose | [Glossary](docs/glossary.md) |

In short: `uv sync --all-extras` then `uv run pytest -q`. The suite needs no
keeper and no provider, because both seams are exercised through doubles.

## What is missing

| Piece | Waiting on |
| --- | --- |
| A provider adapter | A decision about which provider, and a sitting with it. `Concluding` is satisfied by whatever a deployment's profile builds, and nothing in this repository builds one. Until a second adapter exists, the rule that no adapter may import a sibling ranges over a single file. |
| A reason on a proposal | The keeper, and an argument. The proposal record carries an operation and parameters and no reason, so what a proposal was for lives only in what this printed. The field would have to exist there first, and a record that reads as an explanation and is a generated sentence is worse than no field. |
| A thinker tried against a running keeper | A sitting with one. Every route this reads and writes is checked against a transport that asserts on the request, which is not the same as having watched a proposal land or a held request wake. |
| Any logging at all | A decision about where it goes. Serving writes a line per turn to standard error through a callable the caller supplies, which is the smallest thing that does not decide the question, and it is thin for something that now runs unattended by design. |
| More than one execution at a time | Something asking. One thinking reads one execution, and a thinker that finds its own work answers them one after another rather than together. Whether a case should ever span several is a question nobody has asked. |
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
