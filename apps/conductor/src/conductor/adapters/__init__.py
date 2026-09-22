"""Seam implementations, each importing the library of one outside system.

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

Adding a second control library adds a module here and changes one line at
that entrypoint. Nothing above has to move.
"""
