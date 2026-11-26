"""Setup state, its value objects, and its domain errors.

A Setup is a named set of values a beamline's conductor applies when it
runs an operation, and the schema those values satisfy. A run step
names one by the operation's `config` parameter and may write over some of
its settings with `override`, so a hundred runs with one set of values
repeat none of them and the record still says which set each was asked
to use.

## One per beamline, per operation, by name

The values belong to a place and a routine at once. One processing
routine at two beamlines reads two detectors through two sets of optics,
so its settings differ by beamline, and one beamline runs several
routines whose settings mean nothing to each other. So a setup is keyed
on all three: the beamline, the operation it serves, and a name within
that pair.

## Why the name is a key here when no other name is

An operation's name and a procedure's are labels. Two may share one, and
the id is what anything cites. A setup's name is what a step cites: its
`config` is a string in the operation's parameters, checked against a
pattern and nothing else, so the name is the only handle a step has. Two
setups under one key would leave that step unable to say which it meant.

So the name is held to the alphabet that pattern accepts, which is what
lets every setup be named by a step, and a second definition under a key
already held is refused. The refusal is a check made before the append
rather than a lock, and the defining handler says what that leaves open.

## Revised, never edited

Values change: an axis is recalibrated, a filter is swapped. A change is
a revision with the next number, carrying the whole of the new values and
their schema, and every earlier revision stays readable by folding the
stream that far. An edit in place would leave whatever used the old values
pointing at values nobody can read back.

A revision names the revision it was made against, and is refused unless
that is still the latest; `SetupCannotBeRevisedError` says why.

## The settings schema is required, and the settings close it

`settings_schema` is a JSON Schema in the subset
docs/reference/conventions.md describes, one property per setting, and
pairs with an operation's `parameters_schema` the way the naming page's
R3 draws a schema: the family noun and a descriptor. That subset cannot
close an object, because it has no keyword refusing an undeclared
property, so a setup closes it by comparing keys: every setting is
described, every description has a value, and the values satisfy the
descriptions.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from keeper.shared.bounded_text import bounded_name
from keeper.shared.json_schema.validation import (
    validate_schema_declaration,
    validate_values_against_schema,
)

SETUP_NAME_MAX_LENGTH = 200
"""How long a setup name may be.

Matches `OPERATION_NAME_MAX_LENGTH`, so a reader comparing a setup with the
operation it serves finds one bound rather than two.
"""

SETUP_NAME_PATTERN = "^[a-z0-9][a-z0-9-]*$"
"""The alphabet a setup name is held to: lowercase letters, digits and hyphens.

The same pattern the facility register puts on an operation's `config`
parameter, written out here rather than read from there, because the
register lives outside this project and the published repository has to
stand without it. Holding every name to it is what lets every setup be
named by a step.
"""

SETUP_BEAMLINE_MAX_LENGTH = 100
"""How long the beamline a setup belongs to may be.

Matches `PROCEDURE_BEAMLINE_MAX_LENGTH`, because the two name the same
beamlines, in the form the descriptor directories use, such as `2-bm`.
"""

SETUP_PARAMETERS: frozenset[str] = frozenset({"config", "override"})
"""The two parameters an operation declares when a run of it names a setup.

`config` names the setup and `override` writes over some of its settings
for one run. Both are required rather than either: an operation with a
`config` and no `override` would name values a run could never adjust, and
one with an `override` and no `config` would adjust values nothing named.
"""

_NAME = re.compile(SETUP_NAME_PATTERN)


class InvalidSetupNameError(ValueError):
    """A setup name was over the bound or outside its alphabet.

    A `ValueError`, like every name refusal here: the input was never
    well-formed, which is the split that sends this to 400. The message says
    which of the two it was, because a caller fixing either is choosing a
    different name and should know what to choose.
    """

    def __init__(self, value: str) -> None:
        if len(value) > SETUP_NAME_MAX_LENGTH:
            reason = f"it is {len(value)} characters and the bound is {SETUP_NAME_MAX_LENGTH}"
        else:
            reason = f"{value!r} is not lowercase letters, digits and hyphens"
        super().__init__(
            f"A setup name is what a step's config parameter carries, so it must match "
            f"{SETUP_NAME_PATTERN}: {reason}"
        )


class InvalidSetupBeamlineError(ValueError):
    """A beamline was empty, whitespace-only, or over the length bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Beamline must be 1 to {SETUP_BEAMLINE_MAX_LENGTH} characters after "
            f"trimming (got {len(value.strip())})"
        )


class InvalidSetupSettingsSchemaError(ValueError):
    """The settings schema is not one this system will store.

    Carries the reason, which names the keyword or the setting at fault. The
    message is the operator's only guide to fixing the document they sent,
    so it is passed through rather than replaced with a generic line, the
    way an operation's schema refusal is.
    """


class InvalidSetupSettingsError(ValueError):
    """The settings do not match the settings schema they arrived with.

    Two ways to fail: a key on one side with no partner on the other, or a
    value the schema refuses. One class for both, because both are fixed by
    editing the same two documents, and the message names the settings at
    fault.
    """


class SetupNotFoundError(Exception):
    """A command or query named a setup id with no stream behind it."""

    def __init__(self, setup_id: UUID) -> None:
        super().__init__(f"Setup {setup_id} not found")
        self.setup_id = setup_id


class SetupRevisionNotFoundError(Exception):
    """A read asked for a revision this setup has not reached.

    Carries the revision the setup is at, so a caller is told how far it
    goes rather than only that it does not go that far.
    """

    def __init__(self, setup_id: UUID, revision: int, latest: int) -> None:
        super().__init__(
            f"Setup {setup_id} has no revision {revision}: its revisions run from 1 to {latest}"
        )
        self.setup_id = setup_id
        self.revision = revision
        self.latest = latest


class SetupAlreadyExistsError(Exception):
    """A definition named a setup that already exists.

    The ordinary way here is a second definition under a key one setup
    already holds: the same name, for the same operation, at the same
    beamline. A step names a setup by that key, so a second one under it
    would leave the step unable to say which it meant. The refusal carries
    the id of the setup already there, which is the one to revise instead.

    The other way is unreachable through the ordinary path: a definition
    aimed at an id that already has a stream, which a defining handler
    cannot produce because it mints a fresh id. It is the same fact said of
    an id rather than of a key, and the decider states it so that it relies
    on nothing it has not checked.
    """

    def __init__(self, setup_id: UUID) -> None:
        super().__init__(
            f"Setup {setup_id} already exists, and a setup is revised rather than defined twice"
        )
        self.setup_id = setup_id


class SetupCannotBeRevisedError(Exception):
    """A revision was made against a revision that is not the latest, or changed nothing.

    One class for the two, per R6 in docs/reference/naming.md: one verb is
    refused, and the two numbers it carries tell the reasons apart, the way
    `ExecutionCannotBeClaimedError` carries the status that tells a contest
    from a late arrival. `revision` is the revision the setup is at, and
    `expected_revision` the one the caller said it was revising.

    When the two differ, the caller read some other revision than the
    latest, and its values were decided against something no longer true.
    Its next move is to read the setup again and decide again. Refused
    rather than written, because a revision landing over one its author
    never saw would discard that one's change without anybody choosing to.

    When they agree, the revision repeats the one it follows, and there is
    nothing to write: a revision is read as a change, and one identical to
    the revision before it would say values changed when none did.
    """

    def __init__(self, setup_id: UUID, revision: int, expected_revision: int) -> None:
        if expected_revision != revision:
            reason = (
                f"the revision was made against revision {expected_revision}, and the setup "
                f"is at revision {revision}; read it again and revise what it holds now"
            )
        else:
            reason = (
                f"these are the settings and the settings schema of revision {revision} already"
            )
        super().__init__(f"Setup {setup_id} cannot be revised: {reason}")
        self.setup_id = setup_id
        self.revision = revision
        self.expected_revision = expected_revision


class OperationCannotTakeSetupError(Exception):
    """A setup was defined for an operation no run of which could name one.

    Named for the operation, because the operation's parameters are the
    fact the caller has to act on. Defined here, because what makes an
    operation able to take a setup is this aggregate's idea: the operation
    is the older record and knows nothing of setups, and `SETUP_PARAMETERS`
    is where the two parameters it needs are written down.
    """

    def __init__(self, operation_id: UUID) -> None:
        super().__init__(
            f"Operation {operation_id} cannot take a setup: its parameters do not declare "
            "both config and override, so no run of it could name one"
        )
        self.operation_id = operation_id


class SetupCannotBePinnedError(Exception):
    """A dispatch could not pin a step to the latest revision of the setup it names.

    Two ways to get here. No setup holds the name the step's `config`
    carries, for the step's operation at the procedure's beamline, or the
    step's `override` does not fit that setup's latest revision. Either way
    there is no revision this system can say the step runs with, and an
    execution handed out without one would leave a conductor applying
    values nobody chose.

    One class for both, because both are fixed the same way: define the
    setup the step names, or revise it so the override fits, and dispatch
    again. A procedure is never edited, so the setup is what moves.

    A 409 rather than a 400. The step was well-formed when its procedure
    was defined; what it names is missing or has changed since, which is
    a fact about state, and the same dispatch succeeds once the state does.

    Carries the index of the step, because a procedure may hold several
    runs, and the reason, which names the setup, the beamline and the
    setting.
    """

    def __init__(self, index: int, reason: str) -> None:
        super().__init__(f"Step {index}'s setup cannot be pinned: {reason}")
        self.index = index
        self.reason = reason


@dataclass(frozen=True)
class SetupName:
    """What a step's config parameter calls this setup.

    Not trimmed, unlike every other name in this context. A step's `config`
    is matched against the pattern as it was written, with nothing trimming
    it first, so a name trimmed here would be a name no step could carry.
    Anything outside the alphabet is refused instead, surrounding spaces
    included.

    Checked on construction, so the check runs once in the decider on the
    way in and again in the evolver on the way back out of the log.
    `fullmatch` rather than `match`, because the pattern's `$` would
    otherwise accept a name ending in a newline.
    """

    value: str

    def __post_init__(self) -> None:
        if len(self.value) > SETUP_NAME_MAX_LENGTH or _NAME.fullmatch(self.value) is None:
            raise InvalidSetupNameError(self.value)


@bounded_name(max_length=SETUP_BEAMLINE_MAX_LENGTH, error_class=InvalidSetupBeamlineError)
@dataclass(frozen=True)
class SetupBeamline:
    """Which beamline holds this setup.

    Trimmed and length-bounded on construction, and checked against nothing
    else, for the reason a procedure's beamline is: there is no Beamline
    aggregate, and a second register of which beamlines exist would be a
    thing to keep in step for no reader's benefit.
    """

    value: str


@dataclass(frozen=True)
class Setup:
    """A setup at one revision, as the fold leaves it.

    `revision` is 1 at definition and one more for each revision since. The
    fold computes it from the stream, and each revision event carries the
    number it makes, so the two are compared on the way through rather than
    one being trusted.

    `settings` and `settings_schema` are the whole of what that revision said.
    Neither is a difference from the revision before it: a revision is
    readable on its own, without folding anything earlier to find out what
    it left unchanged.
    """

    id: UUID
    beamline: SetupBeamline
    operation_id: UUID
    name: SetupName
    settings: dict[str, Any]
    settings_schema: dict[str, Any]
    revision: int


def can_take_a_setup(parameters_schema: Mapping[str, Any]) -> bool:
    """Whether an operation's parameters let a run of it name a setup.

    Asked of the schema rather than of the operation, so this module needs
    nothing from the operation's own. An operation takes a setup when its
    parameters declare both of `SETUP_PARAMETERS`; what each of them must
    hold is the operation's to say, and nothing here reads it.
    """
    properties = parameters_schema.get("properties")
    if not isinstance(properties, Mapping):
        return False
    return set(cast("Mapping[str, Any]", properties)) >= SETUP_PARAMETERS


def named_setup(parameters: Mapping[str, Any]) -> SetupName | None:
    """The setup a run's parameters name in `config`, or None when they name none.

    None covers a `config` that is absent, one that is not a string, and
    one outside the alphabet a setup name is held to, because none of the
    three is a name any setup could hold. What that means is the caller's
    to say: a run of an operation that takes a setup and names none is
    refused by `setup_refusal`.
    """
    config = parameters.get("config")
    if not isinstance(config, str):
        return None
    try:
        return SetupName(config)
    except InvalidSetupNameError:
        return None


def setup_refusal(
    parameters: Mapping[str, Any],
    setups: Mapping[tuple[UUID, SetupName], Setup],
    *,
    operation_id: UUID,
    beamline: str,
) -> str | None:
    """Why a run of a setup-taking operation cannot run with the setup it names, or None.

    Asked only of a run whose operation `can_take_a_setup`; a run of any
    other operation names no setup and nothing here applies to it.

    `setups` is what the caller resolved for the procedure's beamline,
    keyed by operation and name. A run whose `config` names nothing, or
    names a key absent from it, is refused, and so is a run whose
    `override` does not fit the setup it found: the override may hold only
    settings the setup's schema describes, each satisfying its
    description, and none of them is required. An absent override is an
    empty one.

    The reason names the setup, the beamline and the setting, so each
    caller can raise it as its own refusal: a definition and a dispatch
    refuse the same fact with different errors.

    A setup in `setups` held at some other beamline is a caller bug rather
    than a refusal, because the caller resolved it there, so it raises a
    plain `ValueError` no handler can trip.
    """
    name = named_setup(parameters)
    if name is None:
        return (
            f"operation {operation_id} takes a setup, and the run's config names none a "
            "step could carry"
        )
    setup = setups.get((operation_id, name))
    if setup is None:
        return (
            f"no setup named {name.value} holds values for operation {operation_id} at {beamline}"
        )
    if setup.beamline.value != beamline:
        msg = f"a setup held at {setup.beamline.value} was resolved for a run at {beamline}"
        raise ValueError(msg)
    return _override_refusal(parameters.get("override", {}), setup)


class _OverrideRefusedError(ValueError):
    """What the shared validator raises here, before the setup is named."""


def _override_refusal(override: object, setup: Setup) -> str | None:
    """Why an override does not fit a setup's revision, or None when it does.

    Validated as a partial object: the setup's own property descriptions,
    with nothing required, and the keys compared first because the schema
    subset cannot refuse an undescribed one.
    """
    where = f"setup {setup.name.value} at {setup.beamline.value}, revision {setup.revision}"
    if not isinstance(override, Mapping):
        return f"its override is not an object of settings for {where}"
    given = cast("Mapping[str, Any]", override)
    described: dict[str, Any] = setup.settings_schema["properties"]
    undescribed = sorted(set(given) - set(described))
    if undescribed:
        return f"its override names {undescribed}, which {where} does not hold"
    partial: dict[str, Any] = {"type": "object", "properties": described}
    try:
        validate_values_against_schema(given, partial, error_class=_OverrideRefusedError)
    except _OverrideRefusedError as refused:
        return f"its override does not satisfy {where}: {refused}"
    return None


def validate_settings_schema(settings_schema: dict[str, Any]) -> None:
    """Refuse a settings schema this system will not store.

    The shared declarer-side check comes first and holds the draft, the
    keyword subset, the unit annotations and that the document compiles.
    Then three things a setup's schema needs beyond being a schema: it
    describes an object, it describes at least one setting, and it gives
    every setting a type. A setting with no type is one the schema would
    accept a value of any kind for, which tells a conductor nothing about
    what it is applying.

    Called by both deciders, on a definition and on every revision.
    """
    validate_schema_declaration(settings_schema, error_class=InvalidSetupSettingsSchemaError)
    if settings_schema.get("type") != "object":
        msg = "A setup's settings schema must describe an object, with one property per setting"
        raise InvalidSetupSettingsSchemaError(msg)
    properties: dict[str, Any] = settings_schema.get("properties") or {}
    if not properties:
        msg = "A setup's settings schema must describe at least one setting"
        raise InvalidSetupSettingsSchemaError(msg)
    untyped = sorted(name for name, described in properties.items() if "type" not in described)
    if untyped:
        msg = f"Every setting in a settings schema needs a type, and these have none: {untyped}"
        raise InvalidSetupSettingsSchemaError(msg)


def validate_settings(settings: Mapping[str, Any], settings_schema: dict[str, Any]) -> None:
    """Refuse settings that do not match the settings schema they arrived with.

    Keys first, because the schema subset cannot close an object: a schema
    accepts a value it does not describe, so comparing the two key sets is
    what closes it. A setting with no description is refused, and so is a
    description with no setting. Then the values, through the shared
    carrier-side validator, which names the setting and the constraint.

    Assumes a schema `validate_settings_schema` has accepted, so the
    properties are there to compare against.
    """
    described = set(settings_schema["properties"])
    given = set(settings)
    undescribed = sorted(given - described)
    if undescribed:
        msg = f"These settings have no description in the settings schema: {undescribed}"
        raise InvalidSetupSettingsError(msg)
    unset = sorted(described - given)
    if unset:
        msg = f"These settings are described in the settings schema and given no value: {unset}"
        raise InvalidSetupSettingsError(msg)
    validate_values_against_schema(settings, settings_schema, error_class=InvalidSetupSettingsError)


def same_document(left: Any, right: Any) -> bool:
    """Whether two JSON documents say the same thing, by JSON's equality rather than Python's.

    Python's `==` holds `True == 1`, so a setting changed from `1` to `true`
    would compare equal and the revision making that change would be
    refused as changing nothing. JSON keeps a boolean apart from a number
    and keeps `1` and `1.0` together, which is the reading a JSON Schema
    validator applies to `enum`, and the one a revision is compared by.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        left_object = cast("dict[str, Any]", left)
        right_object = cast("dict[str, Any]", right)
        return left_object.keys() == right_object.keys() and all(
            same_document(value, right_object[key]) for key, value in left_object.items()
        )
    if isinstance(left, list) and isinstance(right, list):
        left_array = cast("list[Any]", left)
        right_array = cast("list[Any]", right)
        return len(left_array) == len(right_array) and all(
            same_document(one, other) for one, other in zip(left_array, right_array, strict=True)
        )
    return bool(left == right)


__all__ = [
    "SETUP_BEAMLINE_MAX_LENGTH",
    "SETUP_NAME_MAX_LENGTH",
    "SETUP_NAME_PATTERN",
    "SETUP_PARAMETERS",
    "InvalidSetupBeamlineError",
    "InvalidSetupNameError",
    "InvalidSetupSettingsError",
    "InvalidSetupSettingsSchemaError",
    "OperationCannotTakeSetupError",
    "Setup",
    "SetupAlreadyExistsError",
    "SetupBeamline",
    "SetupCannotBePinnedError",
    "SetupCannotBeRevisedError",
    "SetupName",
    "SetupNotFoundError",
    "SetupRevisionNotFoundError",
    "can_take_a_setup",
    "named_setup",
    "same_document",
    "setup_refusal",
    "validate_settings",
    "validate_settings_schema",
]
