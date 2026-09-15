"""Shared length bound for operator free-text reasons.

A `reason` is the free-text justification an operator or an agent
attaches to a state-changing or terminal command: aborting something,
retiring something, refusing something. Every such reason is capped at
the same length, and this module is the one home for that bound.

This is deliberately separate from the per-value-object `MAX_LENGTH`
constants described in `aroc.shared.bounded_text`. Those bound named
value objects and stay local to each aggregate, so one can be retuned on
its own. A reason is not a value object: it is a bare validated string,
checked in the decider and again at the API boundary, and the same bound
applies across every aggregate. Shared, not per-aggregate.

A reason is also the field most likely to carry personal data by
accident, since an operator writing prose may name someone. See the
personal-data convention in docs/reference/conventions.md before adding
a reason field to an event payload.
"""

REASON_MAX_LENGTH = 500


__all__ = ["REASON_MAX_LENGTH"]
