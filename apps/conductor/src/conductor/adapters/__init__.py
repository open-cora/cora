"""Seam implementations, each knowing a single outside system.

Most of them import that system's library; `bluesky_acquisition` imports
nothing, because a RunEngine is an object a deployment hands over rather
than a protocol needing an implementation, and what is engine-specific
there is the shape of a call and the names of three document keys. The
rule is about what a module is allowed to know, not about whether it
needs a package to know it.

Everything above this subpackage is free of any of them. `claims`,
`procedure`, `seams`, `conduct` and `outcomes` import the standard library
and each other and nothing else, so the vocabulary a procedure is written
in does not know that Channel Access exists. That is checked rather than
promised, by `tests/test_the_core_names_no_seam.py`.

Nothing here is re-exported from `conductor/__init__.py`, and that is the
other half of the arrangement. Importing `conductor` must not require
pyepics, because a deployment driving a Tango beamline has no reason to
install it. An adapter is reached by its own module path, at the
entrypoint that chooses it:

    from conductor.adapters.epics_control import EpicsControl

Adding a second control library, or a second engine, adds a module here
and changes one line at that entrypoint. Nothing above has to move.
"""
