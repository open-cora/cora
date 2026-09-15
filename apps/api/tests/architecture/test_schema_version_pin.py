"""`EXPECTED_SCHEMA_VERSION` must name the newest tracked migration.

The constant is hand-maintained on purpose: the runtime image does not ship
the migrations directory, so there is nothing on disk for the process to read
at boot. This test is what keeps the hand-maintained value honest, moving the
cost of forgetting onto CI rather than onto a deployment that refuses to start.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import pytest

from aroc.infrastructure.schema_version import EXPECTED_SCHEMA_VERSION, parse_versions
from tests.architecture.conftest import tracked_migration_files

pytestmark = pytest.mark.architecture


def test_expected_schema_version_matches_the_newest_migration() -> None:
    migrations = tracked_migration_files()
    assert migrations, "No tracked migrations found; the pin has nothing to check against."

    versions = parse_versions(migrations)
    newest = max(versions)
    assert newest == EXPECTED_SCHEMA_VERSION, (
        f"EXPECTED_SCHEMA_VERSION is {EXPECTED_SCHEMA_VERSION!r} but the newest "
        f"tracked migration is {newest!r}. Update the constant in "
        "aroc/infrastructure/schema_version.py in the same commit as the migration."
    )


def test_every_migration_filename_parses_as_a_version() -> None:
    """A filename Atlas cannot order is a migration that applies at the wrong time."""
    migrations = tracked_migration_files()
    versions = parse_versions(migrations)
    assert len(versions) == len(migrations), (
        "Some migration filenames did not parse as a YYYYMMDDHHMMSS version. "
        "Atlas orders by that prefix; a file without one applies unpredictably."
    )
