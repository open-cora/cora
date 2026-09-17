# Glossary

Each term defined once and used the same way in code, commits, and prose. Names are load-bearing; drift in vocabulary is drift in the model. If a page uses a term differently, the page is wrong.

The glossary currently covers the chassis only. Domain vocabulary is added as each bounded context lands, and a term is not in the model until it is here.

## Project name

- **AROC.** This project. A parallel modeling effort on the architecture described in these pages. The name mirrors its sibling [CORA](https://github.com/xmap/cora), and so does the expansion: CORA reads "Continuously Overpromised, Rarely Automated"; AROC reads "Automated Rarely, Overpromised Continuously".
- **CORA.** The sibling project this chassis was copied from. AROC owns its copy outright; the two share no code and are free to diverge. When these pages cite a convention as inherited, CORA is where it came from.

## Architecture

- **Bounded context (BC).** A self-contained slice of the domain with its own model, language, and API surface. One Python package under `aroc/`.
- **Aggregate.** Consistency boundary inside a BC. Holds state, validates commands, emits events.
- **Decider.** Pure `(state, command) -> events`. Business rules. No I/O.
- **Evolver.** Pure `(state, event) -> state`. Folds events into state.
- **Fold-on-read.** Rebuild aggregate state by replaying its events on every command. No snapshots.
- **Vertical slice.** One folder per command or query: `command.py`, `decider.py`, `handler.py`, `route.py`, `tool.py`.
- **FCIS.** Functional core, imperative shell. Pure deciders and evolvers; all I/O at the shell through injected ports.
- **Port.** A `Protocol` defining a side-effect seam: `Clock`, `IdGenerator`, `EventStore`, `Authorize`, `IdempotencyStore`, `TokenVerifier`, and the rest.
- **Adapter.** A concrete implementation of a port. Named `<Tech><Port>`, with no suffix: `PostgresEventStore`, `JwtTokenVerifier`, `InMemoryIdempotencyStore`.
- **Kernel.** The shared kernel: the cross-BC primitives every `wire_<bc>(deps)` pulls from. Settings, clock, id generator, authorize, event store, idempotency store, connection pool.
- **Composition root.** `infrastructure/deps.py` plus `api/main.py`. The only place that constructs adapters and binds them to ports.
- **Handler.** The imperative shell for one slice: loads state, calls the pure decider, appends the resulting events. Not an endpoint; the route is the endpoint.
- **Wire.** A BC's `wire.py`, which builds the BC's handler bundle from the kernel. Also the verb for that act.

## Events

- **Event store.** Append-only Postgres table of immutable events. INSERT-only at the database role level, not merely by convention.
- **Stream.** All events for one aggregate instance, ordered by version.
- **Stream type.** The aggregate kind a stream belongs to. Routing is on `(stream_type, event_type)`, never `event_type` alone.
- **Position.** Global monotonic ordinal of an event in the store. Subject to a bigserial sequence-rollback hazard that projections must handle.
- **transaction_id (xid8).** Postgres transaction identifier carried on every event. Lets a projection worker advance a cursor without skipping in-flight inserts.
- **Envelope.** The persistence wrapper around a domain event: stream coordinates, correlation and causation ids, principal, timestamps and schema version.
- **Projection.** A read model built by replaying events into a denormalized table. Workers tail the store and advance a bookmark.
- **Bookmark.** A projection's durable cursor in `projection_bookmarks`.
- **Entries table.** A typed append-only table for rows a slice writes directly, without a decider. Distinct from `events`: events record what was decided, entries record what was done.
- **Upcaster.** A `from_stored` dispatch arm that reads an older payload shape. Introduced only once a second breaking change hits the same logical event.

## Surfaces

- **REST.** FastAPI HTTP endpoints under `/<resource>`. OpenAPI at `/docs`.
- **MCP.** Model Context Protocol, the agent surface. Streamable HTTP at `/mcp`. Same handler as REST, never a parallel implementation.
- **Surface id.** Identifies the ingress shape a call arrived through. Threads through every handler, the `Authorize` port, and the idempotency cache key namespace.
- **Principal.** The authenticated caller, as a UUID. Set by the bearer middleware, or by a verifying proxy on the header path.

## Testing

- **Fitness function.** An architecture test that asserts a structural rule rather than a behavior. Lives in `tests/architecture/`, does no I/O.
- **Vacuous pass.** A fitness function that passes because it found nothing to check. The default state of this repository until the first BC lands, and the reason `test_fitness_scope.py` exists.
- **Tier.** One of the five test directories: `unit`, `architecture`, `integration`, `contract`, `e2e`. The marker is the category; the test name is the property.
- **Create-style slice.** A slice whose verb is `define_*`, `register_*`, or `add_*`. Introduces a new stream, so it carries an idempotency key and a Postgres-backed handler test.

## Conventions

- **Rule of three.** Promote a shared abstraction only after three real usages with identical, stable invariants. Applies to value objects, handler factories, ports, and helper modules.
- **Forward-only.** A migration is never edited after it has been applied anywhere. A rollback is a new compensating migration.
- **Genesis event.** The first event on a stream. A template emits `<X>Defined`; an instance emits `<X>Registered`.
