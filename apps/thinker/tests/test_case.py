"""Pairing what a procedure asked for with what the record says became of it."""

from __future__ import annotations

import pytest

from thinker.case import MismatchedCaseError, Reading, assemble


def _assembled(
    *,
    asked: tuple[tuple[str, dict[str, object]], ...],
    became: dict[str, str | None],
    ended: bool = True,
    objective: str | None = None,
):
    return assemble(
        Reading(
            execution_id="exec-1",
            procedure="a scan",
            asked=asked,
            became=became,
            ended=ended,
        ),
        objective=objective,
    )


def test_assemble_pairs_each_step_with_the_outcome_reported_against_it() -> None:
    case = _assembled(
        asked=(("s1", {"kind": "move"}), ("s2", {"kind": "acquire"})),
        became={"s1": "Done", "s2": "Broken"},
    )
    assert [(step.step_id, step.became) for step in case.steps] == [
        ("s1", "Done"),
        ("s2", "Broken"),
    ]


def test_assemble_joins_by_id_rather_than_by_position() -> None:
    """The check the whole signature exists for.

    A record that came back in a different order from the procedure would
    pair every step with the wrong outcome under a positional join, and
    would say nothing while doing it.
    """
    case = _assembled(
        asked=(("s1", {"kind": "move"}), ("s2", {"kind": "acquire"})),
        became={"s2": "Broken", "s1": "Done"},
    )
    assert [step.became for step in case.steps] == ["Done", "Broken"]


def test_assemble_numbers_steps_in_the_procedures_order() -> None:
    case = _assembled(
        asked=(("c", {}), ("a", {}), ("b", {})),
        became={},
    )
    assert [(step.index, step.step_id) for step in case.steps] == [(0, "c"), (1, "a"), (2, "b")]


def test_assemble_keeps_a_step_the_record_says_nothing_about() -> None:
    """The ordinary shape of a run that stopped early, not an error."""
    case = _assembled(
        asked=(("s1", {}), ("s2", {}), ("s3", {})),
        became={"s1": "Done"},
    )
    assert [step.became for step in case.steps] == ["Done", None, None]


def test_assemble_passes_the_procedures_own_description_through_unchanged() -> None:
    declared: dict[str, object] = {"kind": "acquire", "plan_id": "p-9", "scopes": ["motor:x"]}
    case = _assembled(asked=(("s1", declared),), became={"s1": "Done"})
    assert case.steps[0].asked == declared


def test_assemble_refuses_an_outcome_reported_against_no_step() -> None:
    with pytest.raises(MismatchedCaseError, match="does not list"):
        _assembled(asked=(("s1", {}),), became={"s1": "Done", "ghost": "Done"})


def test_assemble_names_every_orphaned_step_in_its_refusal() -> None:
    """A message naming one of three sends a reader looking for one problem."""
    with pytest.raises(MismatchedCaseError) as refusal:
        _assembled(asked=(("s1", {}),), became={"x": "Done", "y": "Done", "z": "Done"})
    assert "x, y, z" in str(refusal.value)


def test_assemble_carries_the_objective_it_was_given() -> None:
    case = _assembled(asked=(("s1", {}),), became={}, objective="find the edge")
    assert case.objective == "find the edge"


def test_assemble_leaves_the_objective_empty_when_the_caller_gave_none() -> None:
    assert _assembled(asked=(("s1", {}),), became={}).objective is None


def test_unreached_returns_only_the_steps_with_no_outcome() -> None:
    case = _assembled(
        asked=(("s1", {}), ("s2", {}), ("s3", {})),
        became={"s1": "Done", "s3": "Skipped"},
    )
    assert [step.step_id for step in case.unreached()] == ["s2"]


def test_unreached_is_empty_when_every_step_reported() -> None:
    case = _assembled(asked=(("s1", {}),), became={"s1": "Refused"})
    assert case.unreached() == ()


def test_ran_to_the_end_is_true_when_every_step_has_an_outcome() -> None:
    case = _assembled(asked=(("s1", {}), ("s2", {})), became={"s1": "Done", "s2": "Done"})
    assert case.ran_to_the_end()


def test_ran_to_the_end_ignores_which_outcome_each_step_got() -> None:
    """A procedure whose every step was refused still reached its last one."""
    case = _assembled(asked=(("s1", {}), ("s2", {})), became={"s1": "Refused", "s2": "Broken"})
    assert case.ran_to_the_end()


def test_ran_to_the_end_is_false_when_a_step_reported_nothing() -> None:
    case = _assembled(asked=(("s1", {}), ("s2", {})), became={"s1": "Done"})
    assert not case.ran_to_the_end()


def test_ran_to_the_end_and_ended_answer_different_questions() -> None:
    """An execution closed early has outcomes for only some of its steps.

    Collapsing the two would make a thinker read a run that was stopped as
    a run that finished, which is the reading the case type exists to make
    hard.
    """
    stopped = _assembled(asked=(("s1", {}), ("s2", {})), became={"s1": "Done"}, ended=True)
    assert stopped.ended
    assert not stopped.ran_to_the_end()

    walked = _assembled(
        asked=(("s1", {}), ("s2", {})), became={"s1": "Done", "s2": "Done"}, ended=False
    )
    assert not walked.ended
    assert walked.ran_to_the_end()
