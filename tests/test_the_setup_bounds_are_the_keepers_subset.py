"""The keywords a setup's bounds may use, against the schema subset the keeper accepts.

`beamlines/seed_setups.py` works a setup's schema out of a register and
copies each bound onto the setting it names, refusing any keyword outside
`BOUNDS` before anything is sent. The keeper refuses a schema using any
keyword outside `ALLOWED_SCHEMA_KEYS`, in
`apps/keeper/src/keeper/shared/json_schema/subset.py`. A bound is a
property's own constraint, so the two sets should differ by exactly the
keywords that structure a schema rather than constrain a value.

Nothing else reads both. If the keeper widened its subset, the register
could not use the new keyword; if it narrowed it, the seeder would offer a
keyword the keeper then refuses, as a 400 on a real run rather than as a
refusal on a dry one. Read rather than imported, because this tier
installs neither.
"""

from __future__ import annotations

import ast
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]
SEEDER = TREE / "beamlines" / "seed_setups.py"
SUBSET = TREE / "apps" / "keeper" / "src" / "keeper" / "shared" / "json_schema" / "subset.py"

STRUCTURAL = frozenset({"$schema", "type", "required", "properties"})
"""The keywords that shape a schema rather than constrain one value.

`type` among them because the seeder works it out from the value and a
bound may not override it.
"""


def _string_set(module: Path, name: str) -> frozenset[str]:
    """The strings in a module-level `frozenset({...})` assigned to `name`."""
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == name and isinstance(value, ast.Call):
            (members,) = value.args
            assert isinstance(members, ast.Set), f"{name} is no longer built from a set literal"
            return frozenset(
                str(member.value) for member in members.elts if isinstance(member, ast.Constant)
            )
    raise AssertionError(f"{module.relative_to(TREE)} no longer declares {name}")


def test_both_sides_still_declare_what_this_rule_compares() -> None:
    assert _string_set(SEEDER, "BOUNDS")
    assert _string_set(SUBSET, "ALLOWED_SCHEMA_KEYS") >= STRUCTURAL


def test_a_bound_may_use_every_constraint_the_keeper_accepts_and_nothing_else() -> None:
    accepted = _string_set(SUBSET, "ALLOWED_SCHEMA_KEYS")

    assert _string_set(SEEDER, "BOUNDS") == accepted - STRUCTURAL
