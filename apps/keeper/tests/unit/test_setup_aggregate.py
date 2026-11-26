"""The Setup aggregate: its value objects, its checks, its fold, and its round trip.

The name is the value object here that differs from its siblings, because
it is the one a step carries, so it is held to an alphabet rather than
trimmed. The fold is the other half worth reading: a revision carries its
number and the fold compares it, and every earlier revision is read back
by folding only that far.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.setup import (
    SETUP_BEAMLINE_MAX_LENGTH,
    SETUP_NAME_MAX_LENGTH,
    SETUP_STREAM_TYPE,
    InvalidSetupBeamlineError,
    InvalidSetupNameError,
    InvalidSetupSettingsError,
    InvalidSetupSettingsSchemaError,
    Setup,
    SetupBeamline,
    SetupDefined,
    SetupName,
    SetupRevised,
    can_take_a_setup,
    fold,
    fold_revisions,
    from_stored,
    named_setup,
    same_document,
    setup_refusal,
    to_payload,
    validate_settings,
    validate_settings_schema,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number", "unit": {"system": "udunits", "code": "pixel"}},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
    },
}

_SETTINGS: dict[str, Any] = {"rotation-axis": 1630.0, "binning": 2}


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=SETUP_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _defined(name: str = "tomo-default") -> SetupDefined:
    return SetupDefined(
        setup_id=uuid4(),
        beamline="2-bm",
        operation_id=uuid4(),
        setup_name=name,
        settings=dict(_SETTINGS),
        settings_schema=dict(_SETTINGS_SCHEMA),
        occurred_at=_WHEN,
    )


def _revised(defined: SetupDefined, revision: int, axis: float) -> SetupRevised:
    return SetupRevised(
        setup_id=defined.setup_id,
        revision=revision,
        settings={**_SETTINGS, "rotation-axis": axis},
        settings_schema=dict(_SETTINGS_SCHEMA),
        occurred_at=_WHEN,
    )


@pytest.mark.parametrize("name", ["tomo-default", "a", "19bm-binned-2", "0", "x" * 200])
def test_a_setup_name_in_the_config_alphabet_is_accepted(name: str) -> None:
    assert SetupName(name).value == name


@pytest.mark.parametrize(
    "name",
    ["", "-leading", "Tomo", "tomo_default", "tomo default", " tomo", "tomo ", "tomo.v2"],
)
def test_a_setup_name_outside_the_config_alphabet_is_refused(name: str) -> None:
    with pytest.raises(InvalidSetupNameError, match="lowercase letters, digits and hyphens"):
        SetupName(name)


def test_a_setup_name_ending_in_a_newline_is_refused() -> None:
    """The pattern ends in `$`, which in Python's `re` also matches before a
    final newline. A step's config is matched by a JSON Schema validator,
    for which the end is the end, so a name passing here with a newline on
    it would be one no step could carry."""
    with pytest.raises(InvalidSetupNameError):
        SetupName("tomo\n")


def test_a_setup_name_over_the_bound_is_refused_and_says_how_long_it_was() -> None:
    with pytest.raises(InvalidSetupNameError, match=f"the bound is {SETUP_NAME_MAX_LENGTH}"):
        SetupName("x" * (SETUP_NAME_MAX_LENGTH + 1))


def test_a_setup_name_is_not_trimmed() -> None:
    """Trimming would store a name no step could carry, since nothing trims
    a step's config before matching it. A name with a space is refused."""
    with pytest.raises(InvalidSetupNameError):
        SetupName("  tomo-default  ")


def test_a_setup_beamline_is_trimmed_on_construction() -> None:
    assert SetupBeamline("  2-bm  ").value == "2-bm"


def test_a_setup_beamline_that_is_blank_or_over_the_bound_is_refused() -> None:
    with pytest.raises(InvalidSetupBeamlineError):
        SetupBeamline("   ")
    with pytest.raises(InvalidSetupBeamlineError):
        SetupBeamline("x" * (SETUP_BEAMLINE_MAX_LENGTH + 1))


def test_an_operation_declaring_config_and_override_can_take_a_setup() -> None:
    schema = {"properties": {"config": {"type": "string"}, "override": {"type": "object"}}}

    assert can_take_a_setup(schema)


@pytest.mark.parametrize(
    "schema",
    [
        {"properties": {"config": {"type": "string"}}},
        {"properties": {"override": {"type": "object"}}},
        {"properties": {}},
        {"$schema": "https://json-schema.org/draft/2020-12/schema"},
    ],
)
def test_an_operation_missing_either_parameter_cannot_take_a_setup(schema: dict[str, Any]) -> None:
    assert not can_take_a_setup(schema)


def test_a_settings_schema_in_the_subset_with_typed_settings_is_accepted() -> None:
    validate_settings_schema(dict(_SETTINGS_SCHEMA))


@pytest.mark.parametrize(
    ("settings_schema", "said"),
    [
        ({"type": "object", "properties": {"a": {"type": "number"}}}, "2020-12"),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/a"}},
            },
            "forbidden keyword",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "array",
                "properties": {"a": {"type": "number"}},
            },
            "describe an object",
        ),
        (
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
            "at least one setting",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {},
            },
            "at least one setting",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"minimum": 0}},
            },
            r"these have none: \['b'\]",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"a": "number"},
            },
            "must be a schema dict",
        ),
        (
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "a": {"type": "number", "unit": {"system": "imperial", "code": "in"}}
                },
            },
            "allowed namespace",
        ),
    ],
    ids=[
        "no-draft",
        "forbidden-keyword",
        "not-an-object",
        "no-properties",
        "empty-properties",
        "untyped-setting",
        "setting-not-a-schema",
        "unit-outside-the-allowlist",
    ],
)
def test_a_settings_schema_a_setup_cannot_hold_is_refused_with_the_reason(
    settings_schema: dict[str, Any], said: str
) -> None:
    with pytest.raises(InvalidSetupSettingsSchemaError, match=said):
        validate_settings_schema(settings_schema)


def test_settings_matching_their_settings_schema_are_accepted() -> None:
    validate_settings(dict(_SETTINGS), dict(_SETTINGS_SCHEMA))


def test_a_setting_the_settings_schema_does_not_describe_is_refused() -> None:
    """The subset cannot close an object, so the key comparison is what
    refuses a setting nobody described. A schema alone would accept it."""
    with pytest.raises(InvalidSetupSettingsError, match=r"no description.*\['filter'\]"):
        validate_settings({**_SETTINGS, "filter": "Al"}, dict(_SETTINGS_SCHEMA))


def test_a_described_setting_with_no_value_is_refused() -> None:
    with pytest.raises(InvalidSetupSettingsError, match=r"given no value: \['binning'\]"):
        validate_settings({"rotation-axis": 1630.0}, dict(_SETTINGS_SCHEMA))


def test_a_value_the_settings_schema_refuses_is_refused_and_names_the_setting() -> None:
    with pytest.raises(InvalidSetupSettingsError, match="binning"):
        validate_settings({**_SETTINGS, "binning": 3}, dict(_SETTINGS_SCHEMA))


def test_json_equality_keeps_a_boolean_apart_from_a_number() -> None:
    """Python's `==` would call these the same, and a revision turning a
    setting from 1 into true would then be refused as changing nothing."""
    assert not same_document({"flag": 1}, {"flag": True})
    assert not same_document([0], [False])


def test_json_equality_keeps_an_integer_with_the_same_number_written_as_a_float() -> None:
    assert same_document({"axis": 1630}, {"axis": 1630.0})


def test_json_equality_compares_nested_documents_by_key_and_by_position() -> None:
    assert same_document({"a": [1, {"b": "x"}]}, {"a": [1, {"b": "x"}]})
    assert not same_document({"a": [1, 2]}, {"a": [2, 1]})
    assert not same_document({"a": 1}, {"a": 1, "b": 2})


def test_the_stored_payload_carries_the_name_under_a_qualified_key() -> None:
    """`setup_name` rather than `name` is what keeps this row past the
    personal-data check, and that check reads the event class, not this
    dict, so the payload is asserted on its own."""
    event = _defined()

    assert to_payload(event) == {
        "setup_id": str(event.setup_id),
        "beamline": "2-bm",
        "operation_id": str(event.operation_id),
        "setup_name": "tomo-default",
        "settings": _SETTINGS,
        "settings_schema": _SETTINGS_SCHEMA,
        "occurred_at": _WHEN.isoformat(),
    }


def test_both_events_survive_the_round_trip_through_their_stored_payloads() -> None:
    defined = _defined()
    revised = _revised(defined, 2, 1631.5)

    assert from_stored(_stored("SetupDefined", to_payload(defined))) == defined
    assert from_stored(_stored("SetupRevised", to_payload(revised))) == revised


def test_folding_the_genesis_gives_revision_one_of_what_it_describes() -> None:
    event = _defined()

    setup = fold([event])

    assert setup is not None
    assert setup.id == event.setup_id
    assert setup.beamline == SetupBeamline("2-bm")
    assert setup.operation_id == event.operation_id
    assert setup.name == SetupName("tomo-default")
    assert setup.settings == _SETTINGS
    assert setup.settings_schema == _SETTINGS_SCHEMA
    assert setup.revision == 1


def test_a_revision_replaces_the_values_and_moves_the_number_and_nothing_else() -> None:
    defined = _defined()

    setup = fold([defined, _revised(defined, 2, 1631.5)])

    assert setup is not None
    assert setup.revision == 2
    assert setup.settings == {**_SETTINGS, "rotation-axis": 1631.5}
    assert (setup.id, setup.beamline, setup.operation_id, setup.name) == (
        defined.setup_id,
        SetupBeamline("2-bm"),
        defined.operation_id,
        SetupName("tomo-default"),
    )


def test_a_revision_that_does_not_follow_the_one_before_it_cannot_be_folded() -> None:
    """The number on the event and the number the fold counts are compared,
    so a row out of order or edited stops the fold rather than being
    believed."""
    defined = _defined()

    with pytest.raises(ValueError, match="carries revision 3 onto a setup at revision 1"):
        fold([defined, _revised(defined, 3, 1631.5)])


def test_a_revision_on_an_empty_stream_cannot_be_folded() -> None:
    with pytest.raises(ValueError, match="SetupRevised cannot be applied to empty state"):
        fold([_revised(_defined(), 2, 1631.5)])


def test_folding_the_revisions_keeps_each_one_as_it_was_written() -> None:
    defined = _defined()

    revisions = fold_revisions(
        [defined, _revised(defined, 2, 1631.5), _revised(defined, 3, 1632.0)]
    )

    assert [setup.revision for setup in revisions] == [1, 2, 3]
    assert [setup.settings["rotation-axis"] for setup in revisions] == [1630.0, 1631.5, 1632.0]


def test_folding_an_empty_stream_gives_no_setup_and_no_revisions() -> None:
    assert fold([]) is None
    assert fold_revisions([]) == ()


def test_the_folded_documents_are_not_the_payload_dicts_they_came_from() -> None:
    """Shallow copy on fold, so neither side can mutate the other. An
    aliasing bug here is silent until something writes through one
    reference and changes the other."""
    event = _defined()

    setup = fold([event])

    assert setup is not None
    assert setup.settings is not event.settings
    assert setup.settings_schema is not event.settings_schema


def test_a_stored_row_of_an_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Setup event_type"):
        from_stored(_stored("SetupRetired", to_payload(_defined())))


def test_a_stored_row_missing_a_field_is_refused_by_event_not_by_field() -> None:
    payload = to_payload(_defined())
    del payload["setup_name"]

    with pytest.raises(ValueError, match="Malformed SetupDefined"):
        from_stored(_stored("SetupDefined", payload))


def test_a_stored_revision_whose_number_is_not_a_number_is_refused_by_event() -> None:
    defined = _defined()
    payload = to_payload(_revised(defined, 2, 1631.5))
    payload["revision"] = "second"

    with pytest.raises(ValueError, match="Malformed SetupRevised"):
        from_stored(_stored("SetupRevised", payload))


def test_a_stored_row_whose_name_no_longer_passes_fails_the_fold() -> None:
    """Re-validation on the way out, not just on the way in. Unreachable
    through the API today, and reachable the day the alphabet narrows."""
    payload = to_payload(_defined())
    payload["setup_name"] = "Tomo Default"

    with pytest.raises(InvalidSetupNameError):
        fold([from_stored(_stored("SetupDefined", payload))])


_OPERATION_ID = UUID(int=21)


def _held(*, beamline: str = "2-bm", revision: int = 1) -> Setup:
    return Setup(
        id=UUID(int=22),
        beamline=SetupBeamline(beamline),
        operation_id=_OPERATION_ID,
        name=SetupName("tomo-default"),
        settings=dict(_SETTINGS),
        settings_schema=dict(_SETTINGS_SCHEMA),
        revision=revision,
    )


def _refusal(parameters: dict[str, Any], *, held: Setup | None = None) -> str | None:
    setup = held or _held()
    return setup_refusal(
        parameters,
        {(_OPERATION_ID, setup.name): setup},
        operation_id=_OPERATION_ID,
        beamline="2-bm",
    )


def test_a_config_in_the_name_alphabet_names_that_setup() -> None:
    assert named_setup({"config": "tomo-default"}) == SetupName("tomo-default")


@pytest.mark.parametrize(
    "parameters",
    [{}, {"config": 7}, {"config": "Tomo Default"}, {"config": None}],
    ids=["absent", "not-a-string", "outside-the-alphabet", "null"],
)
def test_a_config_no_setup_could_hold_names_none(parameters: dict[str, Any]) -> None:
    assert named_setup(parameters) is None


def test_a_run_naming_a_held_setup_with_no_override_fits_it() -> None:
    """An absent override is an empty one, so the setup's values run as they are."""
    assert _refusal({"config": "tomo-default"}) is None


def test_an_override_holding_some_of_the_described_settings_fits() -> None:
    """Partial on purpose: nothing in an override is required, because the
    setup already holds a value for every setting it describes."""
    assert _refusal({"config": "tomo-default", "override": {"binning": 4}}) is None


def test_a_run_whose_config_names_no_setup_is_refused_and_says_which_operation() -> None:
    reason = _refusal({"override": {"binning": 4}})

    assert reason is not None
    assert str(_OPERATION_ID) in reason
    assert "names none" in reason


def test_a_run_naming_a_setup_nobody_holds_is_refused_naming_it_and_the_beamline() -> None:
    reason = _refusal({"config": "flat-field"})

    assert reason is not None
    assert "flat-field" in reason
    assert "2-bm" in reason
    assert str(_OPERATION_ID) in reason


def test_an_override_naming_a_setting_the_setup_does_not_describe_is_refused_naming_it() -> None:
    reason = _refusal({"config": "tomo-default", "override": {"binning": 2, "dark-fields": 10}})

    assert reason is not None
    assert "dark-fields" in reason
    assert "binning" not in reason
    assert "tomo-default" in reason
    assert "2-bm" in reason


def test_an_override_value_the_description_refuses_is_refused_naming_the_revision() -> None:
    reason = _refusal(
        {"config": "tomo-default", "override": {"binning": 3}}, held=_held(revision=4)
    )

    assert reason is not None
    assert "binning" in reason
    assert "revision 4" in reason


def test_an_override_that_is_not_an_object_of_settings_is_refused() -> None:
    reason = _refusal({"config": "tomo-default", "override": ["binning", 2]})

    assert reason is not None
    assert "not an object" in reason


def test_a_setup_resolved_at_another_beamline_is_a_caller_bug_not_a_refusal() -> None:
    """The caller resolved it at the beamline it passed, so a mismatch is
    that caller's mistake, and no reason given to a client could fix it."""
    with pytest.raises(ValueError, match="resolved for a run at 2-bm"):
        _refusal({"config": "tomo-default"}, held=_held(beamline="32-id"))
