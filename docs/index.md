# AROC

Automated Rarely, Overpromised Continuously.

An event-sourced system of record, built on the chassis from its sibling project [CORA](https://github.com/xmap/cora) and modelling its own domains. Nothing is published yet; this repository is local.

## Where the documentation stands

One bounded context exists. Most of the reference pages were carried over with the chassis and describe rules that are real, with examples that are still placeholders.

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

No tutorial and no how-to guides. Nothing describes deployment, because there is nowhere to deploy to yet. There is no page on the chassis itself, so how the event store, the idempotency wrapper and the kernel fit together is currently readable only from the code and its docstrings.

## What the code looks like today

```
   bounded contexts    1     Access
   aggregates          1     Actor
   operations          4     register, deactivate, reactivate, read
   tests             575     unit 273, architecture 216, contract 29, integration 57
```

The architecture tier is unusually large for the size of the domain, and that is deliberate. Those tests check the shape of the codebase rather than its behaviour: that every slice carries the modules its shape requires, that no event payload can hold personal data, that a stored name cannot be renamed without noticing, and that every test declares which lane runs it.
