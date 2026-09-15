# Reference

For humans and LLM agents writing AROC code, and for code reviewers. Not a tutorial. The rules to honor when modifying AROC so the codebase does not drift. If the code disagrees with this page, the code is wrong.

These conventions were inherited from the sibling project [CORA](https://github.com/xmap/cora) along with the chassis, then stripped of that project's domain vocabulary. The rules are the same; the examples are placeholders until AROC has bounded contexts of its own to draw them from.

## Pages

| Page | Subject |
| --- | --- |
| [Workflow](workflow.md) | Reading order, commits, branch flow, migrations, tests |
| [Layout](layout.md) | BC structure, slice shapes, imports, shared code |
| [Modeling](modeling.md) | Event sourcing, value objects, field grouping |
| [Patterns](patterns.md) | Read side, query slices, projections, idempotency, cross-aggregate validation, rejections |
| [Conventions](conventions.md) | Identifiers, units, personal data, schema-validated values, documentation |
| [Naming](naming.md) | Aggregates, events, commands, slices, ports, URLs |
| [Runtime](runtime.md) | Production hardening, logging, HTTP errors |
| [Glossary](glossary.md) | Terms defined once and used the same way in code, commits, and prose |

## A note on the empty state

The baseline carries zero bounded contexts. Every rule below that ranges over BCs, aggregates, or slices therefore describes a shape nothing currently has. The architecture fitness tests in `apps/api/tests/architecture/` are in the same position: they pass by finding nothing to check.

That is a false negative, not a green light. `test_fitness_scope.py` pins the discovered-BC count so the first real BC fails it on purpose, forcing a conscious look at whether the fitness suite now ranges over something real.
