"""Operation schemas, against the subset the keeper will actually accept.

`beamlines/operations.toml` declares a JSON Schema per operation and the
keeper validates it on the way in, refusing anything outside a narrow
subset with a 400 that names neither the offending keyword nor the
property it sits on.

The subset is small and unobvious. It has no `additionalProperties` and
no `exclusiveMinimum`, both of which are ordinary JSON Schema and both
of which a reasonable author reaches for. A `$schema` naming Draft
2020-12 is mandatory. None of that is discoverable from the descriptor.

## Why this reads the keeper's constant rather than restating it

A second copy of the allowed set would be a copy nothing compares, which
is the failure this tier exists to catch rather than commit. The set is
read out of the keeper's source, so widening it there widens this
automatically and renaming it fails loudly here.

## What breaks without this

A schema outside the subset is accepted by the descriptor loader, passes
every local test, and is refused the first time anyone seeds it. That is
a round trip to a deployment to learn something a file could have said,
and it already happened once.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

TREE_ROOT = Path(__file__).resolve().parents[1]
_SUBSET = TREE_ROOT / "apps" / "keeper" / "src" / "keeper" / "shared" / "json_schema" / "subset.py"
_OPERATIONS = TREE_ROOT / "beamlines" / "operations.toml"

_ALLOWED = re.compile(
    r"ALLOWED_SCHEMA_KEYS:\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{(.*?)\}", re.S
)
_DRAFT = re.compile(r'DRAFT_2020_12_URI\s*=\s*"([^"]+)"')
_UNIT_SYSTEMS = re.compile(
    r"ALLOWED_UNIT_SYSTEMS:\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{(.*?)\}", re.S
)
_VALIDATION = (
    TREE_ROOT / "apps" / "keeper" / "src" / "keeper" / "shared" / "json_schema" / "validation.py"
)


def _quoted(block: str) -> frozenset[str]:
    return frozenset(re.findall(r'"([^"]+)"', block))


def allowed_keys() -> frozenset[str]:
    found = _ALLOWED.search(_SUBSET.read_text())
    assert found is not None, (
        "could not find ALLOWED_SCHEMA_KEYS in the keeper's subset module. If that "
        "constant moved or was renamed, this check stopped comparing anything "
        "rather than started failing."
    )
    return _quoted(found.group(1))


def draft_uri() -> str:
    found = _DRAFT.search(_SUBSET.read_text())
    assert found is not None, "could not find DRAFT_2020_12_URI in the keeper's subset module"
    return found.group(1)


def allowed_unit_systems() -> frozenset[str]:
    found = _UNIT_SYSTEMS.search(_VALIDATION.read_text())
    assert found is not None, (
        "could not find ALLOWED_UNIT_SYSTEMS in the keeper's validation module"
    )
    return _quoted(found.group(1))


def declared_schemas() -> list[tuple[str, dict[str, Any]]]:
    rows = cast("list[dict[str, Any]]", tomllib.loads(_OPERATIONS.read_text())["operation"])
    return [(str(row["name"]), cast("dict[str, Any]", row["parameters_schema"])) for row in rows]


def walk(node: dict[str, Any], path: str) -> list[tuple[str, dict[str, Any]]]:
    """Every schema node, the way check_subset recurses: into each property."""
    found = [(path, node)]
    properties = node.get("properties")
    if isinstance(properties, dict):
        for name, child in cast("dict[str, Any]", properties).items():
            if isinstance(child, dict):
                found.extend(walk(cast("dict[str, Any]", child), f"{path}.properties.{name}"))
    return found


def test_the_register_declares_a_schema_for_every_operation() -> None:
    schemas = declared_schemas()
    assert schemas, "operations.toml declares nothing, so every check below is vacuous"
    assert all(schema for _, schema in schemas)


@pytest.mark.parametrize("name,schema", declared_schemas())
def test_a_schema_names_the_draft_the_keeper_requires(name: str, schema: dict[str, Any]) -> None:
    assert schema.get("$schema") == draft_uri(), (
        f"{name} must declare $schema as {draft_uri()!r}; the keeper refuses a "
        "declaration without it"
    )


@pytest.mark.parametrize("name,schema", declared_schemas())
def test_a_schema_uses_only_keywords_the_keeper_allows(name: str, schema: dict[str, Any]) -> None:
    permitted = allowed_keys()
    for path, node in walk(schema, name):
        forbidden = set(node) - permitted
        assert not forbidden, (
            f"{path} uses {sorted(forbidden)}, which the keeper's subset refuses. "
            f"It allows only {sorted(permitted)}"
        )


@pytest.mark.parametrize("name,schema", declared_schemas())
def test_a_unit_annotation_has_the_three_field_shape(name: str, schema: dict[str, Any]) -> None:
    systems = allowed_unit_systems()
    for path, node in walk(schema, name):
        raw = node.get("unit")
        if raw is None:
            continue
        assert isinstance(raw, dict), f"{path}.unit must be a table"
        unit = cast("dict[str, Any]", raw)
        assert set(unit) <= {"system", "code", "label"}, f"{path}.unit has extra keys"
        assert unit.get("system") in systems, (
            f"{path}.unit.system is {unit.get('system')!r}; the keeper allows {sorted(systems)}"
        )
        code = unit.get("code")
        assert isinstance(code, str) and code, f"{path}.unit needs a code"
