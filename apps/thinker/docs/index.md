---
template: home.html
---

# Suggests what to run next.

The thinker is where judgement goes. It reads what a run was asked to do and what
became of it, puts the two side by side, hands the whole picture to whatever does
the thinking, and writes the answer down.

**You supply the brain.** There is no AI provider here, no prompt and no model
name. What this settles is the shape of the question and the shape of the answer:
what a reader is given to think about, and which answers it is allowed to give.
Everything behind that is built by whoever deploys it and named in a file.

**It suggests, and never decides.** An answer goes on the record as a suggestion,
and turning a suggestion into real work is a separate act that needs permission
somebody granted. That split is built in rather than a stage to be grown out of.
A facility that runs whatever is suggested has turned advice into an order, and
it has done so outside this repository.

**It cannot interrupt.** Every call goes out and none come in, so an answer
reached while work is still running has nowhere to land. Advice goes on the
record and whatever reads next finds it there.

## Four answers, and why they stay four

| | |
| --- | --- |
| `Propose` | run this next |
| `Stop` | the goal is met, and running more would be waste |
| `Abstain` | nothing here points to a next run that I can see |
| `Refer` | a person should look at this |

`Stop` and `Abstain` are the easiest pair to merge and the most expensive one to
merge. `Stop` is about the goal: it is met. `Abstain` is about the thinker: it
sees no next step. A facility told the second when the first was true keeps
running, and one told the first when the second was true stops early.

All four are written down, along with how much of the run had finished when it
was read, because the same answer means something different at two steps out of
six than at six out of six.

## What it will not claim

**That an answer is any good.** There is no confidence score and no self-rating,
and there will not be one. A thinker rating its own answer produces exactly what
this system refuses everywhere else, where a thing reporting on itself was taken
for a finding about the thing. A number a thinker gives itself looks like a
measurement and is an opinion.

**That a failure is an abstention.** Nothing is swallowed. A record it cannot
reach and a provider that crashed both stop the thinking, and neither turns into
an answer. Returning `Abstain` after a failure would read as a thinker that
looked and found nothing, when it is a thinker that did not look.

## The pages

**Running one**, if you have to install one and invoke it.

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | The two ways to name a question, how to configure one, and what each exit status means |

**Understanding it**, if you want to know what it does and why.

| Page | What it answers |
| --- | --- |
| [Thinking](thinking.md) | What one thinking promises, what it is given to read, and which answers the record can hold |
| [Architecture](architecture.md) | The pieces this settles on, one run drawn end to end, and who decides what |
| [Contract](client-contract.md) | The agreement this keeps at its edge: three routes, and the key the two halves join on |
| [Glossary](glossary.md) | The words shared with the record, and what each one is pinned to |

**Changing it**, if you are editing the code.

| Page | What it answers |
| --- | --- |
| [Naming](naming.md) | What a name has to do before it is allowed in |
| [Conventions](conventions.md) | What a docstring is for, what a comment has to earn, what a page may claim |
| [Workflow](workflow.md) | Commits, branches, and what a test has to be called |

This project is newer than the others published from the same tree and it says so
where it matters. Where a decision here came from measurement, the measurement
was somebody else's and is named as theirs; where it came from reasoning, the
page says that rather than borrowing a number to sound settled.
