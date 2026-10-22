"""What a step holds while it runs, pinned spelling by spelling.

A set derives its claim from the record it names and a run declares one.
The derivation is the half with no second chance: an author writes a
record and gets whatever `Scope.record` makes of it, so anything that
moves that derivation has to reproduce this table exactly or it has
quietly widened or narrowed holds that nothing downstream checks.

The separator rows are the ones that matter. `Step.setting` reads every
record through `Scope.record` and never through `Scope.parse`, so a name
written with a trailing separator claims that one record rather than
everything beneath it. A derivation reaching for `parse` instead would
turn such a row into a hold over a whole device family, which conflicts
with far more than it did and refuses steps that never collided. A run
declaring the same text does get the namespace, and that asymmetry is
deliberate: one is derived from a name and the other is an author saying
what a routine touches.
"""

from __future__ import annotations

import pytest

from conductor.claims import Claim, Scope
from conductor.procedure import Procedure, Step

DERIVED = (
    ("2bmb:m1", "2bmb:m1"),
    ("2bmb:m1.VAL", "2bmb:m1"),
    ("2bmb:m1.STOP", "2bmb:m1"),
    ("2bmb:m10", "2bmb:m10"),
    ("  2bmb:m1  ", "2bmb:m1"),
    ("2bmb:cam1:", "2bmb:cam1"),
    ("2bmb:TomoScan:Energy", "2bmb:TomoScan:Energy"),
)
"""Every spelling a set may carry, and the one scope name it derives."""


@pytest.mark.parametrize(("written", "claimed"), DERIVED)
def test_a_set_claims_the_single_record_its_spelling_names(written: str, claimed: str) -> None:
    assert Step.setting(record=written, value=1.0).claim == Claim(
        scopes=frozenset({Scope(name=claimed, covers_beneath=False)})
    )


def test_a_set_written_with_a_trailing_separator_claims_no_namespace() -> None:
    held = Step.setting(record="2bmb:cam1:", value=1.0).claim
    assert not held.conflicts_with(Claim.over("2bmb:cam1:Acquire"))


def test_a_run_declaring_a_trailing_separator_claims_the_whole_namespace() -> None:
    held = Step(routine="tomo_scan", claim=Claim.over("2bmb:cam1:")).claim
    assert held.conflicts_with(Claim.over("2bmb:cam1:Acquire"))


def test_a_run_claims_exactly_the_scopes_its_author_declared() -> None:
    declared = Claim.over("2bmb:m1", "2bmb:cam1:")
    assert Step(routine="tomo_scan", claim=declared).claim == declared


def test_a_procedure_holds_one_claim_for_each_step_in_order() -> None:
    procedure = Procedure(
        name="align",
        steps=(
            Step.setting(record="2bmb:TomoScan:Energy", value=92.0),
            Step(routine="tomo_scan", claim=Claim.over("2bmb:m1", "2bmb:cam1:")),
            Step.setting(record="2bmb:m1.VAL", value=0.0),
        ),
    )
    assert [step.claim for step in procedure.steps] == [
        Claim.over("2bmb:TomoScan:Energy"),
        Claim.over("2bmb:m1", "2bmb:cam1:"),
        Claim.over("2bmb:m1"),
    ]
