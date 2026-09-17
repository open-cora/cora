"""A length bound declared in Python must equal the one declared in SQL.

An aggregate bounds a display name with a constant. The migration bounds
the same column with a CHECK. They are written in two languages, in two
files, by two acts, and nothing makes them agree.

A Python bound LOOSER than the database one fails at write time, in
production, on a value long enough to reach it and short enough that
nobody tried it. A bound TIGHTER than the database one is harmless but
means the CHECK is dead. Either way the two should be read together, and
this is the only place that reads them together.

Both sides are independent here in the sense that matters: the constant
is not derived from the SQL, and the SQL is not generated from the
constant, so their agreement is evidence rather than arithmetic.
"""

import re

import pytest

from aroc.access.aggregates.actor import ACTOR_NAME_MAX_LENGTH
from tests.architecture.conftest import tracked_migration_files

pytestmark = pytest.mark.architecture

_PROFILE_NAME_CHECK = re.compile(
    r"name\s+text\s+NOT NULL\s+CHECK\s*\(length\(name\)\s*<=\s*(\d+)\)"
)


def _declared_profile_name_bounds() -> list[int]:
    """Every name-column length bound declared across the migrations."""
    return [
        int(match.group(1))
        for path in tracked_migration_files()
        for match in _PROFILE_NAME_CHECK.finditer(path.read_text())
    ]


def test_the_migrations_declare_a_profile_name_length_bound() -> None:
    """Guard the parse: a regex that matches nothing agrees with everything."""
    assert _declared_profile_name_bounds(), (
        "No profile-name length CHECK was found in any migration. Either the "
        "column lost its constraint, or this check's pattern no longer matches "
        "how the constraint is written, in which case it has been silently "
        "comparing an empty list."
    )


def test_the_actor_name_bound_equals_the_profile_column_bound() -> None:
    for declared in _declared_profile_name_bounds():
        assert declared == ACTOR_NAME_MAX_LENGTH, (
            f"ACTOR_NAME_MAX_LENGTH is {ACTOR_NAME_MAX_LENGTH} but a migration "
            f"constrains the profile name column to {declared}. A looser Python "
            "bound fails at the database on the write path; a tighter one makes "
            "the CHECK unreachable. Change both together."
        )
