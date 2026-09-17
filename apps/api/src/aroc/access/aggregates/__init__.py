"""Aggregate kernels for the Access bounded context.

The half of this context a sibling may read. A bounded context that
needs a fact about an actor reaches under `aggregates`; it never reaches
into `features`, which holds the slice handlers. That much tach enforces
today, as a declared edge on `aroc.access.aggregates`.

What is NOT settled is how wide the door is. Everything under here is
importable, including `from_stored`, `fold` and the event classes, which
are exported because Access's own slices need them across modules rather
than because a sibling should have them. A sibling holding those could
build an actor event and append it, going around the deciders instead of
through them.

Narrowing that is a job for the first sibling that exists, not a guess
made before one does: tach supports `[[interfaces]]`, which pins the
exposed names, and the set to expose should be read off what a real
consumer imports. Until then this docstring describes a door, not a
contract.
"""
