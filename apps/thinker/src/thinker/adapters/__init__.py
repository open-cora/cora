"""Implementations of the seams, one module per thing being spoken to.

Nothing in `thinker` outside this package imports anything from inside it.
The core names the Protocols in `thinker.seams` and an entrypoint picks
which module here satisfies them, which is what lets a deployment change
its system of record or its provider without the thinking changing.
"""
