---
template: home.html
---

# Suggests what to run next.

The thinker is where judgement goes. It reads what a run was asked to do and what became of it, puts the two side by side, hands the whole picture to whatever does the thinking, and writes the answer down.

## Where this sits

Beamline software assumes somebody is watching. CORA is four programs for the case where nobody is, carrying the three things a person supplied by being present: the judgement about what to run next, the authority that made it permitted, and the account of what was actually done.

| | |
| --- | --- |
| [Keeper](https://github.com/open-cora/keeper) | holds the record, and who may add to it |
| [Conductor](https://github.com/open-cora/conductor) | runs the work at the beamline |
| [Reporter](https://github.com/open-cora/reporter) | reports what happened, and where the data went |
| **Thinker** | suggests what to run next |

**This is where the suggestion comes from**, and the reason it stays a suggestion. [CORA](https://github.com/open-cora/cora) sets out why the four exist and how they fit.

## What it enables

**A facility picks its own model, or no model at all.** There is no AI provider here, no prompt and no model name. What this settles is the shape of the question and the shape of the answer: what a reader is given to think about, and which answers it is allowed to give. Everything behind that is built by whoever deploys it and named in a file.

**A suggestion can be reviewed before it becomes real work.** An answer goes on the record as a suggestion, and turning one into work is a separate act that needs permission somebody granted. A facility that runs whatever is suggested has turned advice into an order, and it has done so outside this repository.

**One program serves a watched session and an unwatched one.** It asks the record for a question nobody has taken up and waits until there is one. Whether a person at a terminal or an agent put the question, it is picked up and answered the same way.

## How

Four answers, and they stay four.

| | |
| --- | --- |
| `Propose` | run this next |
| `Stop` | the goal is met, and running more would be waste |
| `Abstain` | nothing here points to a next run that I can see |
| `Refer` | a person should look at this |

`Stop` and `Abstain` are the easiest pair to merge and the most expensive one to merge. `Stop` is about the goal: it is met. `Abstain` is about the thinker: it sees no next step. A facility told the second when the first was true keeps running, and one told the first when the second was true stops early.

All four are written down, along with how much of the run had finished when it was read, because the same answer means something different at two steps out of six than at six out of six.

**It cannot interrupt.** Every call goes out and none come in, so an answer reached while work is still running has nowhere to land. Advice goes on the record and whatever reads next finds it there.

## What it will not claim

**That an answer is any good.** There is no confidence score and no self-rating, and there will not be one. A thinker rating its own answer produces exactly what this system refuses everywhere else, where a thing reporting on itself was taken for a finding about the thing. A number a thinker gives itself looks like a measurement and is an opinion.

**That a failure is an abstention.** Nothing is swallowed. A record it cannot reach and a provider that crashed both stop the thinking, and neither turns into an answer. Returning `Abstain` after a failure would read as a thinker that looked and found nothing, when it is a thinker that did not look.

## Where it stands today

It finds its own work: serving holds a request open at the record until a question is there, answers it, and asks again. No provider adapter ships here, because that is the deployment's to write. It has not yet been run against a live record.

## The pages

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | The three ways to arrive at a question, how to run one as a service, how to configure one, and what each exit status means |
| [Thinking](thinking.md) | What one thinking promises, what it is given to read, and which answers the record can hold |
| [Architecture](architecture.md) | The pieces this settles on, one run drawn end to end, and who decides what |
| [Contract](client-contract.md) | The agreement this keeps at its edge: the routes it uses, and the key the two halves join on |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |
| [Naming](naming.md), [Conventions](conventions.md), [Workflow](workflow.md) | The rules to keep when editing this code |

This project is newer than the others published from the same tree and it says so where it matters. Where a decision here came from measurement, the measurement was somebody else's and is named as theirs; where it came from reasoning, the page says that rather than borrowing a number to sound settled.
