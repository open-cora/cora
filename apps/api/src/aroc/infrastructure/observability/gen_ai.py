"""GenAI telemetry helpers per OpenTelemetry semantic conventions.

Used by an `LLM` adapter to set the standard `gen_ai.*` span attributes and
emit token and cost metrics from one place. Keeps the adapter free of OTel
imports beyond a single helper call.

## This module records a cost; it does not decide one

`record_llm_call` takes `cost_usd` as a parameter. It does not hold a price
table, and it must not grow one.

A price is a business fact: it changes without any code changing, it differs
per contract, and getting it wrong misreports money. A table of model prices
living here was wrong in two ways at once. It went stale silently, because
nothing in this repository can check a price against the provider. And an
unpriced model degraded quietly: the cost gate returned "no ceiling" and the
dashboard returned $0, so a model missing from the table looked exactly like
a model that cost nothing.

So the seam is: whichever bounded context governs spend owns the prices and
computes the number. Infrastructure records what it is handed. A caller that
cannot price a call passes `None`, and no cost is recorded at all, which
reads as a gap rather than as zero.

## OTel GenAI semantic conventions

Reference: https://opentelemetry.io/docs/specs/semconv/gen-ai/
Current status: experimental. Opt
in is via `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`
in production deploy config. Attribute names below match the spec as
of July 2026 (`gen_ai.system` was deprecated in favour of
`gen_ai.provider.name`; the durable Decision-side record was already
on the new name, this module now matches it); if the spec renames
again, this module is the single edit point.

Attributes set on the active span:
  - `gen_ai.provider.name`     ("anthropic")
  - `gen_ai.operation.name`    ("chat")
  - `gen_ai.request.model`     (the model identifier from `ModelRef`)
  - `gen_ai.request.max_tokens`
  - `gen_ai.response.model`    (the snapshot the provider chose)
  - `gen_ai.response.finish_reasons` (list with one entry today)
  - `gen_ai.usage.input_tokens`
  - `gen_ai.usage.output_tokens`

Anthropic-specific (not in spec yet, included per their cookbook):
  - `gen_ai.usage.cache_creation_input_tokens`
  - `gen_ai.usage.cache_read_input_tokens`

## Cost

`aroc.llm.cost.usd` is a custom histogram (no OTel spec equivalent today).
The value is whatever the caller passes as `cost_usd`; see the note above on
why the price is not computed here. Pass `None` and nothing is recorded, so
an unpriced call leaves a gap in the series rather than a zero that reads as
a free call.

`aroc.llm.concurrent_calls` counts calls that begin while another is still
in flight, via `track_in_flight_call`. It measures the incidence of a race
whose worst case is already characterised but whose frequency is not. See
that tracker's docstring for how to read a zero.

## Metrics

Two histograms and a counter:
  - `gen_ai.client.token.usage`  (per OTel spec: bucketed token counts;
                                  type attribute distinguishes input
                                  vs output vs cache_create vs cache_read)
  - `aroc.llm.cost.usd`          (custom; USD per call, caller-supplied)
  - `aroc.llm.concurrent_calls`  (custom; overlapping-call count)

A meter named `aroc.gen_ai` is created lazily on first use so
modules that import this file without calling its functions don't
register orphan instruments.
"""

from __future__ import annotations

from contextlib import contextmanager
from logging import getLogger
from typing import TYPE_CHECKING

from opentelemetry import metrics

if TYPE_CHECKING:
    from collections.abc import Generator

    from opentelemetry.trace import Span

    from aroc.infrastructure.ports.llm import LLMUsage, ModelRef

_log = getLogger(__name__)


_meter = metrics.get_meter("aroc.gen_ai")
_token_histogram = _meter.create_histogram(
    name="gen_ai.client.token.usage",
    unit="{token}",
    description="Token counts per LLM call, by token-type attribute",
)
_cost_histogram = _meter.create_histogram(
    name="aroc.llm.cost.usd",
    unit="USD",
    description="Per-call LLM cost in USD, as supplied by the caller",
)
_concurrent_call_counter = _meter.create_counter(
    name="aroc.llm.concurrent_calls",
    unit="{call}",
    description="LLM calls started while another was already in flight in this process",
)

# Process-local in-flight depth. A plain int is sound here because the LLM
# callers share one event loop (the projection worker runs its subscribers as
# concurrent tasks in a single TaskGroup) and nothing awaits between the read
# and the increment in the tracker below.
_in_flight_calls = 0


@contextmanager
def track_in_flight_call(model_ref: ModelRef) -> Generator[None]:
    """Count LLM calls that begin while another is already in flight.

    This measures the PRECONDITION for a shared-budget race. A spend gate
    that admits a call by reading recorded spend is reading a total that an
    earlier in-flight call has not yet posted to, so two callers can each be
    admitted against a budget that only covers one.

    The worst case is easy to characterise and hard to observe: what is not
    known is how often the window actually opens. A nonzero
    `aroc.llm.concurrent_calls` rate says it opens and the race is real. A
    flat zero across a representative period says it is theoretical in this
    deployment, which is the evidence needed to retire a mitigation rather
    than argue about it.

    Scope: process-local, which is the scope of the race it observes. Calls
    racing from separate replicas are not counted; seeing those would need a
    call start time on the shared record.
    """
    global _in_flight_calls
    if _in_flight_calls > 0:
        _concurrent_call_counter.add(
            1,
            {
                "gen_ai.provider.name": model_ref.provider,
                "gen_ai.request.model": model_ref.model,
            },
        )
    _in_flight_calls += 1
    try:
        yield
    finally:
        _in_flight_calls -= 1


def record_llm_call(
    span: Span,
    *,
    provider_name: str,
    request_model_ref: ModelRef,
    response_model_id: str,
    usage: LLMUsage,
    stop_reason: str,
    max_tokens: int,
    cost_usd: float | None = None,
) -> None:
    """Annotate the active span and emit metrics for one LLM call.

    `cost_usd` is supplied by the caller, which is the only party that knows
    the prices; see the module docstring. Pass `None` when the call cannot be
    priced and no cost is recorded, so the series shows a gap rather than a
    zero that looks like a free call.

    Span attributes are set per the OpenTelemetry GenAI semantic conventions
    in the module docstring.

    The four token-usage metrics are recorded with a `token_type`
    attribute (`input` / `output` / `cache_create` / `cache_read`)
    per the OTel spec convention so a single histogram series can
    be queried by type.

    SAFE TO CALL when the span is the no-op span (the OTel default
    when tracing is disabled): set_attribute is a no-op and the
    histograms are no-op too when no MeterProvider is installed.
    """
    span.set_attribute("gen_ai.provider.name", provider_name)
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.request.model", request_model_ref.model)
    span.set_attribute("gen_ai.request.max_tokens", max_tokens)
    span.set_attribute("gen_ai.response.model", response_model_id)
    span.set_attribute("gen_ai.response.finish_reasons", [stop_reason])
    span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
    span.set_attribute(
        "gen_ai.usage.cache_creation_input_tokens",
        usage.cache_creation_input_tokens,
    )
    span.set_attribute(
        "gen_ai.usage.cache_read_input_tokens",
        usage.cache_read_input_tokens,
    )

    base_attrs = {
        "gen_ai.provider.name": provider_name,
        "gen_ai.request.model": request_model_ref.model,
        "gen_ai.response.model": response_model_id,
    }
    _token_histogram.record(
        usage.input_tokens,
        attributes={**base_attrs, "token_type": "input"},
    )
    _token_histogram.record(
        usage.output_tokens,
        attributes={**base_attrs, "token_type": "output"},
    )
    if usage.cache_creation_input_tokens:
        _token_histogram.record(
            usage.cache_creation_input_tokens,
            attributes={**base_attrs, "token_type": "cache_create"},
        )
    if usage.cache_read_input_tokens:
        _token_histogram.record(
            usage.cache_read_input_tokens,
            attributes={**base_attrs, "token_type": "cache_read"},
        )

    if cost_usd is not None:
        _cost_histogram.record(cost_usd, attributes=base_attrs)


__all__ = [
    "record_llm_call",
    "track_in_flight_call",
]
