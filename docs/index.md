# AROC

Automated Rarely, Overpromised Continuously.

An event-sourced system of record, built on the chassis from its sibling project [CORA](https://github.com/xmap/cora) and modelling its own domains. Nothing is published yet; this repository is local.

## Where the documentation stands

Two bounded contexts exist. Access has a page below; Authority does not yet, and is readable only from its code. Most of the reference pages were carried over with the chassis and describe rules that are real, with examples that are still placeholders.

| Page | Subject | State |
| --- | --- | --- |
| [Access](bounded-contexts/access.md) | The Actor aggregate and its four operations | Current, written against the shipped code |
| [Workflow](reference/workflow.md) | Reading order, commits, migrations, tests, mutation runs | Current |
| [Conventions](reference/conventions.md) | Identifiers, units, personal data, stored names, documentation | Current |
| [Layout](reference/layout.md) | BC structure, slice shapes, imports | Carried, examples are placeholders |
| [Modeling](reference/modeling.md) | Event sourcing, value objects, field grouping | Carried, examples are placeholders |
| [Patterns](reference/patterns.md) | Read side, queries, projections, idempotency | Carried, examples are placeholders |
| [Naming](reference/naming.md) | Aggregates, events, commands, slices, ports, URLs | Carried, examples are placeholders |
| [Runtime](reference/runtime.md) | Hardening, logging, HTTP errors | Carried, examples are placeholders |
| [Glossary](reference/glossary.md) | Terms used the same way in code and prose | Carried |

## What is missing

A page on the Authority context, which now holds the Policy aggregate and the four slices that author a policy, edit one and read one. No tutorial and no how-to guides. Nothing describes deployment, because there is nowhere to deploy to yet. There is no page on the chassis itself, so how the event store, the idempotency wrapper and the kernel fit together is currently readable only from the code and its docstrings.

## What the code looks like today

```
   bounded contexts    2     Access, Authority
   aggregates          2     Actor, Policy
   slices              8     four on Actor, four on Policy
```

Those three are pinned by `test_fitness_scope.py`, so they cannot drift without a test failing. Test counts are not quoted here, because a number in prose goes stale on the next commit and nothing notices.

The architecture tier holds more tests than any other, which is out of proportion to the size of the domain and is deliberate. Those tests check the shape of the codebase rather than its behaviour: that every slice carries the modules its shape requires, that no event payload can hold personal data, that a stored name cannot be renamed without noticing, that every bounded context in the tree is actually mounted in the running app, and that every test declares which lane runs it.

Part of the chassis was copied from the sibling project and has no user here yet. Which modules those are is pinned in `test_unloaded_modules_are_pinned.py` rather than left to be rediscovered, so the day a second context starts using one, the suite says which one.
