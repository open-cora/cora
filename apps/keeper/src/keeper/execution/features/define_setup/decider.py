"""The decision: what defining a setup produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent, and what it
needs from outside its own stream arrives in the context.
"""

from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.operation import OperationCannotBeCitedError
from keeper.execution.aggregates.setup import (
    OperationCannotTakeSetupError,
    Setup,
    SetupAlreadyExistsError,
    SetupBeamline,
    SetupDefined,
    SetupName,
    can_take_a_setup,
    validate_settings,
    validate_settings_schema,
)
from keeper.execution.features.define_setup.command import DefineSetup
from keeper.execution.features.define_setup.context import DefineSetupContext


def decide(
    state: Setup | None,
    command: DefineSetup,
    *,
    context: DefineSetupContext,
    now: datetime,
    new_id: UUID,
) -> list[SetupDefined]:
    """Decide the events produced by defining a setup.

    Invariants:
      - State must be None, or the id already has a history
        -> SetupAlreadyExistsError
      - The name must be within the bound and the alphabet a step's
        config parameter accepts -> InvalidSetupNameError
      - The beamline must be non-empty and within its length bound
        -> InvalidSetupBeamlineError
      - The operation must not have been retired
        -> OperationCannotBeCitedError
      - The operation's parameters must declare both config and override
        -> OperationCannotTakeSetupError
      - No other setup may hold this name for this operation at this
        beamline -> SetupAlreadyExistsError
      - The settings schema must be a schema in the stored subset
        describing an object with at least one setting, each with a type
        -> InvalidSetupSettingsSchemaError
      - The settings must be exactly the settings the schema describes,
        and satisfy it -> InvalidSetupSettingsError

    The order runs from whether this command may be answered at all to
    what it says. The stream check comes first, then the two value
    objects, which are one comparison each. The operation is asked about
    before the key, because a setup for an operation that cannot take one
    is refused whatever it is called, and the key is asked about before the
    settings schema, because a caller told the name is taken should revise
    the setup already there rather than fix a document for a definition
    that will be refused. The schema is checked before the settings,
    because settings checked against a malformed schema tell the caller
    nothing worth fixing.

    That the operation exists is NOT checked here. It needs a store, and
    the handler has already refused a setup for an operation that does
    not. Whether it is retired, and whether it can take a setup, are
    checked here, because the handler hands the operation across whole.

    Whether the key is free is decided from the context rather than read
    here, for the same reason, and the handler says why the answer it
    hands across can be stale.

    A context carrying some other operation than the command names is a
    caller bug rather than a domain refusal, which is why it raises a plain
    `ValueError` the handler cannot trip: the handler loads the operation by
    the command's own id.
    """
    if state is not None:
        raise SetupAlreadyExistsError(state.id)
    operation = context.operation
    if operation.id != command.operation_id:
        msg = (
            f"the context carries operation {operation.id} "
            f"for a command naming {command.operation_id}"
        )
        raise ValueError(msg)
    name = SetupName(command.name)
    beamline = SetupBeamline(command.beamline)
    if operation.is_retired:
        raise OperationCannotBeCitedError(operation.id, operation.status)
    if not can_take_a_setup(operation.parameters_schema):
        raise OperationCannotTakeSetupError(operation.id)
    if context.existing_setup_id is not None:
        raise SetupAlreadyExistsError(context.existing_setup_id)
    validate_settings_schema(command.settings_schema)
    validate_settings(command.settings, command.settings_schema)
    return [
        SetupDefined(
            setup_id=new_id,
            beamline=beamline.value,
            operation_id=command.operation_id,
            setup_name=name.value,
            settings=command.settings,
            settings_schema=command.settings_schema,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
