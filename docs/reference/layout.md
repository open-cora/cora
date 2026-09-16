# Layout

*BC structure, slice shapes, imports, shared code.*

Two axes on purpose: aggregates own the data shape so the domain stays explicit, slices own the use cases so a feature lives in one folder. Modular Monolith on the macro side, Vertical Slice on the micro. Keeping both stops the codebase from collapsing into either pure DDD or pure feature-folders.

## Package layering

```
aroc/
├── shared/           pure value objects and helpers; zero aroc.* imports
├── infrastructure/   ports, adapters, composition root, event-sourcing machinery
├── api/              FastAPI app, middleware, readiness, MCP mount
└── <bc>/             one package per bounded context
```

The contract is declared in `apps/api/tach.toml` and checked by `uv run tach check`:

- `shared` depends on nothing.
- `infrastructure` depends only on `shared`.
- A BC depends on `shared` and `infrastructure`, plus any sibling BC's `aggregates.*` namespace it names.
- `api` depends on every BC.

A BC may reach into a sibling only through that sibling's `aggregates.*` namespace, which is the read-side public surface. Never through `features.*`.

**Read tach.toml as the doors that have been cut, not as a map of what depends on what.** It constrains imports, and imports are only one of several ways one BC comes to depend on another. A `Protocol` declared in `infrastructure.ports`, implemented by one BC's adapter and consumed by another, leaves no import to constrain: both sides name only `infrastructure`, which every module does. An event subscription names its producer with a string. Where the import graph and the dependency graph differ, the dependency graph is the larger one.

`tests/architecture/test_tach_edges_are_used.py` fails on an entry no source file takes up, so a permission whose reason has gone away does not quietly stay. It found one on its first run.

## BC layout

```
aroc/<bc>/
├── __init__.py                       # re-exports public BC surface
├── _bootstrap.py                     # BC-internal constants
├── _projections.py                   # register_<bc>_projections(registry) entry point
├── _<aggregate>_update_handler.py    # update-handler factory hoist (when n>=3 update slices share scaffolding)
├── errors.py                         # BC-application-layer errors
├── routes.py                         # register_<bc>_routes(app)
├── tools.py                          # register_<bc>_tools(mcp, *, get_handlers)
├── wire.py                           # <Bc>Handlers bundle + wire_<bc>(deps)
├── aggregates/
│   └── <aggregate>/
│       ├── state.py                  # state + value objects + domain errors
│       ├── events.py                 # event classes + union + payload helpers
│       ├── evolver.py                # evolve(state, event) + fold(events)
│       ├── read.py                   # load_<aggregate> (fold-on-read)
│       └── <vo_module>.py            # aggregate-internal value objects
├── projections/
│   └── <name>.py                     # read-side projection (consumed by list_* queries)
└── features/
    ├── <verb>_<aggregate>/           # one folder per COMMAND
    │   ├── command.py
    │   ├── decider.py
    │   ├── handler.py
    │   ├── route.py
    │   ├── tool.py
    │   └── context.py                # OPTIONAL: cross-aggregate pre-load before pure decider
    └── get_<aggregate>/              # one folder per QUERY (no decider)
        ├── query.py
        ├── handler.py
        ├── route.py
        └── tool.py
```

Each slice's `__init__.py` re-exports its public surface so callers write `register_thing.bind(deps)`. Events live in the aggregate folder, not the slice: they are intrinsic facts about the aggregate's history.

### Three slice shapes

Three shapes, to be pinned by a slice-contract fitness function once the first slice exists (not written yet, because it would range over nothing):

1. **Command slice**: `__init__, command, decider, handler, route, tool`. Default for state-changing operations that fold through a pure decider.
2. **Query slice**: `__init__, query, handler, route, tool`. No decider; reads from the aggregate or a projection.
3. **Entry-append slice** (`append_<entry>`): `__init__, command, handler, route, tool`. No decider; the handler writes directly to a typed entries store via a per-category port. This shape is indistinguishable from a malformed command slice by file list alone, so whatever pins the contract will need an explicit allowlist of which slices are deliberately decider-free.

### Optional slice files

`context.py` holds a slice-local cross-aggregate pre-load, used when a decider needs sibling-aggregate state. The decider for a context-using slice takes a keyword-only `context: <X>Context` parameter immediately before `now`, where `<X>Context` is a frozen dataclass exported from the slice's `context.py`. The handler builds the context by loading the sibling aggregates and passes it to the pure `decide`; the decider itself never reads from a port.

**Signature-parity `_ = state` discard.** When a context-using decider's own aggregate state lives on the context (either the child is genesis, or the context carries the same state as `state`), the decider opens with `_ = state  # <reason>` to discard the parameter while keeping the signature aligned with single-stream deciders.

### BC-root extras

- `_projections.py`: composition-root entry point that registers the BC's projections with the projection registry. Mechanical, present in every BC that has a `projections/` directory.
- `_<aggregate>_update_handler.py`: factory that hoists shared update-handler scaffolding when n>=3 update slices on the same aggregate share the pattern.
- `_subscribers.py`: wires the BC's domain-event subscribers into the projection registry's subscriber bus.
- `_<aggregate>_dtos.py`: BC-local DTO module re-exported from `routes.py` and `tools.py`, kept out of the slice folder when several read/write slices share the same projected shape.

### Private subpackages (BC-root reshape at scale)

Private `_*.py` modules stay flat at the BC root by default; the naming prefix (`_<aggregate>_<role>.py`) does the grouping. When a BC root crosses ~10 private modules and a cohesive cluster has emerged, carve that cluster into a private subpackage (`_<name>/` with a re-exporting `__init__.py`) so the root stays navigable.

Re-export the public surface so consumers import from the package, not the submodules. The canonical shared-pattern files (`_bootstrap.py`, `_projections.py`, `_<aggregate>_update_handler.py`) stay flat for cross-BC consistency.

**Capability-dependent handlers.** When a slice depends on an external capability that may be unwired in some deployments (for example one that needs `kernel.llm`, which is `None` unless both `LLM_ENABLED` and an API key are set), the handler bundle types the field as `Handler | None`. The route guards on `None` and raises `HTTPException(503)` inline. This is the only documented exception to the rule that command-slice routes do not wrap handler calls.

## Where shared code goes

| Scope | Home |
| --- | --- |
| One aggregate | `aggregates/<aggregate>/state.py`, split when over ~200 lines |
| Across aggregates in one BC | `<bc>/value_objects.py` or `<bc>/_shared/` |
| Across BCs, pure (zero `aroc.*` imports) | `aroc/shared/` |
| Across BCs, depends on ports or the kernel | `aroc/infrastructure/` |

Promote up only after three real usages with identical, stable invariants.
