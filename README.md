# Keeper

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

The keeper is a parallel modeling effort built on a settled architecture: event-sourced
bounded contexts over Postgres, hexagonal ports and adapters, and equivalent REST
and agent-protocol (MCP) surfaces backed by a single handler per command.

The chassis is inherited and deliberately uninteresting. The experiment is the
domains modeled on top of it, and modelling them is what this repository is
doing now.

The name mirrors its sibling [CORA](https://github.com/xmap/cora), and so does the
diagnosis: CORA reads **Continuously Overpromised, Rarely Automated**, and the keeper
reads it back, **Automated Rarely, Overpromised Continuously**.

## Status

**Three bounded contexts, and a client that talks to them.** Access holds actors,
Authority holds the rulebook that says who may issue which command, and Execution
holds plans and the runs that report against them. Every operation is published
twice, as an HTTP route and as an MCP tool, from one handler. Two read models are
maintained by a projection worker.

`apps/reporter/` is the first client: a separate deployable that turns one
engine's document stream into run commands. It reads a live engine and reports
its runs; what it does not yet have is a transport it can replay from, so a
document published while it is down is a document lost. Its README says so.

The counted version of all that lives on the [documentation home
page](docs/index.md), where the numbers are pinned against the fitness suite and
cannot drift. They are not repeated here, because two copies of a count is one
copy and one liability.

## Relationship to CORA

The keeper started from a copy of CORA's chassis and owns it outright from that point on.
There is no shared package, no vendoring registry, and no expectation that a fix in
one lands in the other. The two are free to diverge, including in the plumbing.

What was carried: the event store and its envelope, idempotency, the evolver and
update-handler scaffolding, ports and adapters for the cross-cutting concerns, edge
auth, observability, the test tiers, and the code conventions in
[docs/reference/](docs/reference/index.md).

What was left behind: every domain model. No bounded context here is CORA's, and the
contexts that exist were modelled from questions about a beamline rather than carried
across.

Nothing is claimed about individual words. An earlier version of this section promised
that CORA's facility vocabulary appeared nowhere in the tree, and that was already
untrue: `beam` is a message prefix in the reporter's fixtures, and both projects serve
facilities where a beam, an enclosure and a clearance are the plainest words available.
Two projects reaching the same ordinary noun for the same real thing is convergence,
and the line worth holding is against inheriting a model, not against sharing a
dictionary. What source may not do is explain this tree by describing that one, which
is CLAUDE.md's rule and is enforced by
`apps/keeper/tests/architecture/test_no_sibling_project_vocabulary.py`.

## Quick start

Requires Python 3.13.12 (via uv), Docker (for Postgres), and
[Atlas](https://atlasgo.io/) (for schema migrations).

```bash
make install        # uv sync both projects: apps/keeper and apps/reporter
make precommit      # install git hooks (one-time per clone)
make db-up          # start Postgres on host port 5433
make migrate-apply  # apply the baseline schema
make test           # full suite
make dev            # API at http://localhost:8000, health at /health
```

Postgres binds host port **5433**, not 5432, and the Compose project is named
`keeper` explicitly. Both are so this can run alongside a CORA checkout: the two
repos' compose files sit in identically-named `infra/` directories, so without
an explicit project name Compose treats them as one project and starting either
one stops the other.

## Layout

| Path | Contents |
| --- | --- |
| `apps/keeper/src/keeper/shared/` | Pure value objects and helpers; no ports, no adapters |
| `apps/keeper/src/keeper/infrastructure/` | Ports, adapters, composition root, event-sourcing machinery |
| `apps/keeper/src/keeper/api/` | FastAPI app, middleware, error handlers, MCP mount |
| `apps/keeper/src/keeper/<bc>/` | One package per bounded context, siblings of the two above |
| `apps/keeper/tests/` | Five tiers: unit, architecture, integration, contract, e2e |
| `apps/reporter/` | A client of the API, with its own lockfile and no import of `keeper` |
| `infra/atlas/` | Forward-only schema migrations |
| `spikes/` | Throwaway investigations, each marked with when to delete it |
| `docs/reference/` | Rules for writing code here |

The two applications are separate on purpose. `apps/keeper` is the model and its
surfaces; `apps/reporter` is something that calls them over HTTP and runs where
an engine is rather than where the database is. Neither imports the other, and
separate projects are what make that the interpreter's rule rather than a
convention.

## Contributing

This is a research repository, public to be read rather than to solicit
patches. Corrections and questions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
