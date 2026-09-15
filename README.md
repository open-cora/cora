# AROC

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

AROC is a parallel modeling effort built on a settled architecture: event-sourced
bounded contexts over Postgres, hexagonal ports and adapters, and equivalent REST
and agent-protocol (MCP) surfaces backed by a single handler per command.

The chassis is inherited and deliberately uninteresting. The experiment is the
domains modeled on top of it, which are not yet chosen.

The name mirrors its sibling [CORA](https://github.com/xmap/cora), and so does the
diagnosis: CORA reads **Continuously Overpromised, Rarely Automated**, and AROC
reads it back, **Automated Rarely, Overpromised Continuously**.

## Status

**Baseline only.** The chassis boots, serves health and readiness, applies its
schema, and exposes empty REST and MCP surfaces. There are zero bounded contexts
and zero aggregates. Nothing here is modeled yet.

## Relationship to CORA

AROC started from a copy of CORA's chassis and owns it outright from that point on.
There is no shared package, no vendoring registry, and no expectation that a fix in
one lands in the other. The two are free to diverge, including in the plumbing.

What was carried: the event store and its envelope, idempotency, the evolver and
update-handler scaffolding, ports and adapters for the cross-cutting concerns, edge
auth, observability, the test tiers, and the code conventions in
[docs/reference/](docs/reference/index.md).

What was left behind: every domain noun. CORA's facility vocabulary (beam, clearance,
enclosure, allocation, capture, supply) appears nowhere in this tree.

## Quick start

Requires Python 3.13.12 (via uv), Docker (for Postgres), and
[Atlas](https://atlasgo.io/) (for schema migrations).

```bash
make install        # uv sync inside apps/api
make precommit      # install git hooks (one-time per clone)
make db-up          # start Postgres on host port 5433
make migrate-apply  # apply the baseline schema
make test           # full suite
make dev            # API at http://localhost:8000, health at /health
```

Postgres binds host port **5433**, not 5432, and the Compose project is named
`aroc` explicitly. Both are so this can run alongside a CORA checkout: the two
repos' compose files sit in identically-named `infra/` directories, so without
an explicit project name Compose treats them as one project and starting either
one stops the other.

## Layout

| Path | Contents |
| --- | --- |
| `apps/api/src/aroc/shared/` | Pure value objects and helpers; no ports, no adapters |
| `apps/api/src/aroc/infrastructure/` | Ports, adapters, composition root, event-sourcing machinery |
| `apps/api/src/aroc/api/` | FastAPI app, middleware, error handlers, MCP mount |
| `apps/api/tests/` | Five tiers: unit, architecture, integration, contract, e2e |
| `infra/atlas/` | Forward-only schema migrations |
| `docs/reference/` | Rules for writing code here |

Bounded contexts will live as siblings of `shared/` and `infrastructure/` under
`apps/api/src/aroc/`, one package each.

## License

Apache-2.0. See [LICENSE](LICENSE).
