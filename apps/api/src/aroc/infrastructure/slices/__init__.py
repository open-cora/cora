"""Reusable machinery a bounded context's slices are built from.

A slice is one feature: a command handler, its route, its MCP tool. Each
module here was extracted after the same code had been written out per
aggregate enough times to be worth naming, and each is consumed by slices
rather than by the composition root.

  - `evolver`     folding an event stream back into current state
  - `envelope`    wrapping a domain event for storage
  - `payload`     unwrapping one, with uniform error handling
  - `idempotency` making a retried command safe to repeat
  - `update`      the shape of a single-stream change handler
  - `listing`     the shape of a keyset-paginated query handler
  - `principal`   caller identity inside an MCP tool

Nothing here has a caller yet, which is the expected state of a library
shipped ahead of the domains that use it. Read a low coverage number on
these modules as "no consumer" rather than "untested behaviour".

The split from the rest of `infrastructure/` is by reader: the modules at
the package root describe how the application is assembled and are read
once each, while these are read every time a slice is written.
"""
