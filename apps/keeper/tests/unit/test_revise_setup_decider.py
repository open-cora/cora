"""The decision that revising a setup produces.

A revision is held to everything the first revision was, and to two more
things. It has to be made against the latest revision, so that nobody's
change is written over by somebody who never saw it, and it has to change
something. The last check is the one most easily got wrong, because
Python's equality calls a boolean and a number the same.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.setup import (
    InvalidSetupSettingsError,
    InvalidSetupSettingsSchemaError,
    Setup,
    SetupBeamline,
    SetupCannotBeRevisedError,
    SetupName,
    SetupNotFoundError,
    SetupRevised,
)
from keeper.execution.features.revise_setup import ReviseSetup, decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number"},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
    },
}

_SETTINGS: dict[str, Any] = {"rotation-axis": 1630.0, "binning": 2}


def _setup(
    *,
    revision: int = 1,
    settings: dict[str, Any] | None = None,
    settings_schema: dict[str, Any] | None = None,
) -> Setup:
    return Setup(
        id=uuid4(),
        beamline=SetupBeamline("2-bm"),
        operation_id=uuid4(),
        name=SetupName("tomo-default"),
        settings=dict(settings if settings is not None else _SETTINGS),
        settings_schema=dict(settings_schema if settings_schema is not None else _SETTINGS_SCHEMA),
        revision=revision,
    )


def _revise(
    state: Setup,
    *,
    expected_revision: int | None = None,
    settings: dict[str, Any] | None = None,
    settings_schema: dict[str, Any] | None = None,
) -> list[SetupRevised]:
    """Revise `state`, by default from the revision it is at, with new settings."""
    return decide(
        state,
        ReviseSetup(
            setup_id=state.id,
            expected_revision=(
                expected_revision if expected_revision is not None else state.revision
            ),
            settings=settings if settings is not None else {**_SETTINGS, "binning": 4},
            settings_schema=(
                settings_schema if settings_schema is not None else dict(_SETTINGS_SCHEMA)
            ),
        ),
        now=_NOW,
    )


def test_revising_emits_the_next_revision_carrying_both_documents_whole() -> None:
    state = _setup(revision=3)
    settings = {**_SETTINGS, "rotation-axis": 1631.5}

    events = _revise(state, settings=settings)

    assert events == [
        SetupRevised(
            setup_id=state.id,
            revision=4,
            settings=settings,
            settings_schema=_SETTINGS_SCHEMA,
            occurred_at=_NOW,
        )
    ]


def test_a_revision_changing_only_the_settings_schema_is_accepted() -> None:
    state = _setup()
    wider = {
        **_SETTINGS_SCHEMA,
        "properties": {**_SETTINGS_SCHEMA["properties"], "binning": {"type": "integer"}},
    }

    events = _revise(state, settings=dict(_SETTINGS), settings_schema=wider)

    assert events[0].settings_schema == wider


def test_a_revision_made_against_an_older_revision_is_refused_naming_both() -> None:
    """The stale read the check exists for: the caller read revision 2,
    somebody wrote revision 3, and the caller's values were decided against
    something that is no longer true."""
    state = _setup(revision=3)

    with pytest.raises(
        SetupCannotBeRevisedError, match="made against revision 2, and the setup is at revision 3"
    ) as refused:
        _revise(state, expected_revision=2)

    assert (refused.value.revision, refused.value.expected_revision) == (3, 2)


def test_a_revision_made_against_a_revision_not_yet_written_is_refused() -> None:
    state = _setup(revision=3)

    with pytest.raises(SetupCannotBeRevisedError, match="made against revision 4"):
        _revise(state, expected_revision=4)


def test_a_stale_revision_is_refused_before_its_documents_are_read() -> None:
    """A command decided against an old revision cannot be answered,
    whatever it says, so its author hears that it is stale rather than
    what is wrong with a document it will have to rewrite anyway."""
    state = _setup(revision=3)

    with pytest.raises(SetupCannotBeRevisedError, match="made against revision 2"):
        _revise(state, expected_revision=2, settings_schema={**_SETTINGS_SCHEMA, "type": "array"})


def test_a_revision_that_changes_nothing_is_refused() -> None:
    state = _setup(revision=2)

    with pytest.raises(SetupCannotBeRevisedError, match="of revision 2 already") as refused:
        _revise(state, settings=dict(_SETTINGS))

    assert (refused.value.revision, refused.value.expected_revision) == (2, 2)


def test_a_revision_turning_a_number_into_a_boolean_is_a_change() -> None:
    """`1 == True` in Python, so a comparison by `==` would refuse this as
    changing nothing. JSON keeps the two apart, and so does this."""
    settings_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"dark-fields": {"type": ["integer", "boolean"]}},
    }
    state = _setup(settings={"dark-fields": 1}, settings_schema=settings_schema)

    events = _revise(state, settings={"dark-fields": True}, settings_schema=dict(settings_schema))

    assert events[0].revision == 2


def test_revising_a_setup_that_was_never_defined_is_refused() -> None:
    with pytest.raises(SetupNotFoundError):
        decide(
            None,
            ReviseSetup(
                setup_id=uuid4(),
                expected_revision=1,
                settings=dict(_SETTINGS),
                settings_schema=dict(_SETTINGS_SCHEMA),
            ),
            now=_NOW,
        )


def test_a_revision_with_a_settings_schema_a_setup_cannot_hold_is_refused() -> None:
    state = _setup()

    with pytest.raises(InvalidSetupSettingsSchemaError, match="describe an object"):
        _revise(state, settings_schema={**_SETTINGS_SCHEMA, "type": "array"})


def test_a_revision_dropping_a_described_setting_is_refused() -> None:
    state = _setup()

    with pytest.raises(InvalidSetupSettingsError, match="given no value"):
        _revise(state, settings={"rotation-axis": 1631.5})


def test_a_malformed_revision_is_refused_for_what_is_wrong_before_for_changing_nothing() -> None:
    """A caller sending a broken document hears what is broken about it,
    even when it is the document already stored."""
    state = _setup(settings={"binning": 3})

    with pytest.raises(InvalidSetupSettingsError):
        _revise(state, settings={"binning": 3})
