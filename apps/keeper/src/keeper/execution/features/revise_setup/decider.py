"""The decision: what revising a setup produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.setup import (
    Setup,
    SetupCannotBeRevisedError,
    SetupNotFoundError,
    SetupRevised,
    same_document,
    validate_settings,
    validate_settings_schema,
)
from keeper.execution.features.revise_setup.command import ReviseSetup


def decide(
    state: Setup | None,
    command: ReviseSetup,
    *,
    now: datetime,
) -> list[SetupRevised]:
    """Decide the events produced by revising a setup.

    Invariants:
      - State must not be None, or no such setup was defined
        -> SetupNotFoundError
      - The revision the command was made against must be the latest
        -> SetupCannotBeRevisedError
      - The settings schema must be a schema in the stored subset
        describing an object with at least one setting, each with a type
        -> InvalidSetupSettingsSchemaError
      - The settings must be exactly the settings the schema describes,
        and satisfy it -> InvalidSetupSettingsError
      - The settings or the settings schema must differ from the current
        revision's, by JSON's equality -> SetupCannotBeRevisedError

    The first is unreachable through the handler, which has to read the
    setup before it can authorize against its beamline and refuses an
    absent one there. It is stated anyway, so the decision says what it
    relies on rather than assuming it.

    The revision check comes before the documents are read, because a
    command decided against a revision that is no longer the latest cannot
    be answered whatever it says: its author has not seen what it would
    replace. A stale read is refused with both numbers, which is the
    caller's whole guide to what to do next.

    The two documents are then checked exactly as a definition checks them,
    because a revision is held to everything the first revision was. The
    change check comes last, so that a caller sending a malformed document
    hears what is wrong with it rather than that it changes nothing. By
    then the revision the command was made against is the current one, so
    the change is measured from the revision its author read.

    What is NOT asked is whether the operation is still offered or still
    takes a setup. A revision names no operation; it rewrites values the
    setup already holds for one, and a retired operation is refused
    wherever something new cites it.
    """
    if state is None:
        raise SetupNotFoundError(command.setup_id)
    if command.expected_revision != state.revision:
        raise SetupCannotBeRevisedError(state.id, state.revision, command.expected_revision)
    validate_settings_schema(command.settings_schema)
    validate_settings(command.settings, command.settings_schema)
    if same_document(command.settings, state.settings) and same_document(
        command.settings_schema, state.settings_schema
    ):
        raise SetupCannotBeRevisedError(state.id, state.revision, command.expected_revision)
    return [
        SetupRevised(
            setup_id=state.id,
            revision=state.revision + 1,
            settings=command.settings,
            settings_schema=command.settings_schema,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
