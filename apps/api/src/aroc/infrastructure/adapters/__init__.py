"""Cross-BC infrastructure adapters.

Production implementations of ports defined in `aroc.infrastructure.ports`
that are consumed by multiple BCs (event store, idempotency, profile
store). Naming: the filename is
`snake_case(<Tech><Port>).py`, class is `<Tech><Port>` with no
`Adapter` suffix.
"""
