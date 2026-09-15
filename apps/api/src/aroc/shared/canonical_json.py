"""Single-source canonical JSON encoder for deterministic content hashing.

Stable byte output for the same logical value: sorted keys, no whitespace,
UTF-8 encoded. Both write-time hashing (in a decider) and any later
verification (in a handler, an exporter, a signature check) call this one
helper, so a recorded content-address pin reproduces across processes and
across releases.

It lives in `aroc.shared` rather than in any BC because an aggregates layer
producing canonical bytes for event-payload persistence cannot import from a
BC-local helper module. The shared kernel is the lowest common denominator.

An architecture fitness test restricts bare `json.dumps(sort_keys=True)` to
the few sites that re-export this helper. A second encoder is a second answer
to the same question, and the one that matters is whichever is missing a case.

Callers needing a dict-typed JSON value for persistence wrap as
`json.loads(canonical_json_bytes(...))`. That wrapper stays inline at each
call site rather than being hoisted, so a non-persisting caller does not pay
a parse-then-stringify round trip.
"""

import json


def canonical_json_bytes(value: object) -> bytes:
    """Encode `value` as canonical JSON bytes.

    Equivalent to `json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")`.
    Use this helper everywhere a deterministic byte representation is
    needed for hashing or content-addressed storage in the operation +
    recipe BC trees.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["canonical_json_bytes"]
