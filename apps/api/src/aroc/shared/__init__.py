"""Shared-kernel layer: cross-BC value objects and pure helpers.

Every module here has zero `aroc.*` imports outside `aroc.shared.*` itself:
the purity test that distinguishes shared-kernel from infrastructure. These
are domain primitives (the `Identifier` value object, NewType identity
aliases, bounded-text validators, JSON Schema helpers) usable from any BC
without booting a kernel, opening a connection pool, or touching a port.

Layer dependency direction: `BCs -> infrastructure -> shared`, plus
`BCs -> shared` directly. `aroc.shared` itself depends on nothing under
`aroc.*`, and `apps/api/tach.toml` is what enforces that: planting an
`aroc.infrastructure` import in a module here fails `tach check` and
passes every architecture test. Run the former before trusting the
latter on a layering question.

Modules that depend on ports, the kernel, or adapters belong in
`aroc.infrastructure`, not here.
"""
