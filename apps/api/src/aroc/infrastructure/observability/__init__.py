"""OpenTelemetry wiring and helpers.

Public surface for the rest of the codebase:

- `configure_tracing(settings)`: call once at startup; returns a
  teardown callable that flushes pending spans on shutdown.
- `current_correlation_id()`: derive the request's correlation UUID
  from the active OTel span's trace_id. Used by REST route dependencies
  and MCP tool entrypoints; replaces the prior `asgi-correlation-id`-
  based source.
- `with_tracing(handler, *, command_name, kind)`: composition wrapper
  applied in each BC's wiring module. Adds a span around each command /
  query handler call, sets `aroc.*` attributes, records exceptions.
- `add_trace_context`: structlog processor that injects `trace_id`
  and `span_id` into every log line emitted inside an active span.

Domain and application code never imports OpenTelemetry directly; it
imports from this package, so the choice of telemetry library is local
to one folder and swappable.
"""

from aroc.infrastructure.observability.correlation import current_correlation_id
from aroc.infrastructure.observability.decorator import with_tracing
from aroc.infrastructure.observability.log_processor import add_trace_context
from aroc.infrastructure.observability.provider import (
    Teardown,
    build_tracing,
    configure_tracing,
    instrument_app,
)

# `gen_ai` helpers are NOT re-exported: their only consumer is
# the LLM adapter, which imports
# directly from the submodule. Keeping the package surface focused
# on cross-cutting telemetry primitives (tracing setup, correlation
# id, log processor) makes "what's an AROC observability helper?"
# easy to answer at a glance. If a second LLM adapter needs the
# same helpers, that's the trigger to re-export.

__all__ = [
    "Teardown",
    "add_trace_context",
    "build_tracing",
    "configure_tracing",
    "current_correlation_id",
    "instrument_app",
    "with_tracing",
]
