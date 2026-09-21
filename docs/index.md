# AROC

Automated Rarely, Overpromised Continuously.

An event-sourced system of record, built on the chassis from its sibling project [CORA](https://github.com/xmap/cora) and modelling its own domains. Nothing is published yet; this repository is local.

## Where the documentation stands

Five bounded contexts exist. Access, Execution, Custody and Counsel have pages below; Authority does not yet, and is readable only from its code. Counsel's page is the one written the other way round, before its code rather than after, and then corrected against what landed. The reference pages were carried over with the chassis and describe rules that are real. Most of them now argue from this tree's own contexts; `modeling.md` is the one still working entirely in placeholders, and the table below says which is which.

| Page | Subject | State |
| --- | --- | --- |
| [Access](bounded-contexts/access.md) | The Actor aggregate and its four operations | Current, written against the shipped code |
| [Execution](bounded-contexts/execution.md) | The Plan and Run aggregates, reporting a run an engine performed, and the three ways one ends | Current, written against the shipped code |
| [Custody](bounded-contexts/custody.md) | The Dataset aggregate, and where the data a run produced is being kept | Current, written against the shipped code |
| [Counsel](bounded-contexts/counsel.md) | The Proposal aggregate, what an agent put forward to run next, and whether a run took it | Current, three slices shipped and a fourth designed |
| [Workflow](reference/workflow.md) | Reading order, commits, migrations, tests, mutation runs | Current |
| [Conventions](reference/conventions.md) | Identifiers, units, personal data, stored names, documentation | Current |
| [Layout](reference/layout.md) | BC structure, slice shapes, imports | Carried, examples now from this tree |
| [Modeling](reference/modeling.md) | Event sourcing, value objects, field grouping | Carried, examples are placeholders |
| [Patterns](reference/patterns.md) | Read side, queries, projections, idempotency | Carried, examples now from this tree |
| [Naming](reference/naming.md) | Aggregates, events, commands, slices, ports, URLs | Carried, examples now from this tree |
| [Runtime](reference/runtime.md) | Hardening, logging, HTTP errors | Current, written against the shipped wiring |
| [Glossary](reference/glossary.md) | Terms used the same way in code and prose | Carried |

## What is missing

A page on the Authority context, which holds the Policy aggregate and the four slices that author a policy, edit one and read one. No tutorial and no how-to guides. Nothing describes deployment, because there is nowhere to deploy to yet. There is no page on the chassis itself, so how the event store, the idempotency wrapper and the kernel fit together is currently readable only from the code and its docstrings.

## What the code looks like today

```
   bounded contexts    5     Access, Authority, Execution, Custody, Counsel
   aggregates          6     Actor, Policy, Plan, Run, Dataset, Proposal
   slices             25     four on Actor, four on Policy,
                             three on Plan, eight on Run,
                             three on Dataset, three on Proposal
```

Those three match the integers `test_fitness_scope.py` pins, and `test_docs_match_code_constants.py` compares this block against them, so neither side can drift alone. That check was written after this page said it was pinned and was not: the slice count sat at 15 while the code had 17. Test counts are not quoted here, because a number in prose goes stale on the next commit and nothing notices.

The architecture tier holds more tests than any other, which is out of proportion to the size of the domain and is deliberate. Those tests check the shape of the codebase rather than its behaviour: that every slice carries the modules its shape requires, that no event payload can hold personal data, that a stored name cannot be renamed without noticing, that every bounded context in the tree is actually mounted in the running app, and that every test declares which lane runs it.

Part of the chassis was copied from the sibling project and has no user here yet. Which modules those are is pinned in `test_unloaded_modules_are_pinned.py` rather than left to be rediscovered, so the day a context starts using one, the suite says which one.
