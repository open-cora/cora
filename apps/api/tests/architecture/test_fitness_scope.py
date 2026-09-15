"""Pin what the fitness suite ranges over, so a vacuous pass cannot hide.

Most checks in this directory iterate over discovered bounded contexts. With
none, they iterate over nothing and pass. A green architecture run is
therefore not evidence that any rule HOLDS; it is evidence that the suite ran.

This test makes that state explicit and, more importantly, makes it change
loudly. Adding the first bounded context fails the assertion below on purpose.
When it does:

  1. Confirm the fitness suite now actually ranges over the new package, by
     checking that at least one previously-vacuous test reports collected
     subjects rather than skipping.
  2. Bump `EXPECTED_BC_COUNT` in the same commit.

Doing (2) without (1) converts this guard into bookkeeping. The point is the
look, not the number.
"""

import pytest

from tests.architecture.conftest import discovered_bcs

pytestmark = pytest.mark.architecture

EXPECTED_BC_COUNT = 0
"""Bounded contexts this suite expects to find under `src/aroc`.

Zero is the baseline's honest state. Raise it deliberately, alongside the
check described in the module docstring, never to make a red run green.
"""


def test_discovered_bc_count_matches_the_pinned_expectation() -> None:
    found = discovered_bcs()
    assert len(found) == EXPECTED_BC_COUNT, (
        f"Fitness suite ranges over {len(found)} bounded contexts {found}, "
        f"but EXPECTED_BC_COUNT is {EXPECTED_BC_COUNT}.\n"
        "If you just added a BC: confirm the fitness tests actually see it "
        "(a rule that still collects zero subjects is not enforcing anything), "
        "then bump EXPECTED_BC_COUNT in the same commit."
    )


def test_chassis_packages_are_not_mistaken_for_bounded_contexts() -> None:
    """The BC discovery must exclude the chassis, or every count is wrong.

    Guards the subtraction itself: if `NON_BC_PACKAGES` drifted out of sync
    with the tree, `discovered_bcs()` would report `api`, `infrastructure` and
    `shared` as bounded contexts and the count above would pass for the wrong
    reason.
    """
    found = discovered_bcs()
    for chassis in ("api", "infrastructure", "shared"):
        assert chassis not in found, (
            f"`{chassis}` is chassis, not a bounded context, but BC discovery "
            "returned it. Check NON_BC_PACKAGES in tests/architecture/conftest.py."
        )
