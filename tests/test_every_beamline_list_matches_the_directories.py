"""Every hardcoded list of beamline names, against the one that is the register.

`beamlines/README.md` says this tree is the register of beamline names by
default rather than by declaration: a directory is the name, the keeper
stores it as written, and nothing refuses a name nothing recognises.

Several places spell the list out anyway, because a shell script and a
policy matrix cannot read a directory at the moment they need it. Those
copies were tied to each other in pairs and not to the register, which
left the register free to grow a fifth beamline that two of them would
never hear about.

## What breaks without this, and how quietly

A beamline directory added without a line in the installer gets no token,
so its conductor authenticates as nobody and every call it makes is
refused. One added without a line in the policy matrix gets a token and no
grants, which fails the same way one layer later. Neither is a crash and
neither is logged as a configuration fault: both read as a beamline that
has not been set up yet, which is exactly what it is, with nothing saying
where to look.

## How a beamline name is told from a role name

The lists here hold both. A beamline is named for its sector and station,
so it begins with the sector number; `thinker`, `viewer` and `admin` do
not. That split is the one thing this check assumes about the names, and
it is asserted below rather than left implied.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

TREE_ROOT = Path(__file__).resolve().parents[1]
_BEAMLINES = TREE_ROOT / "beamlines"
_MATRIX = TREE_ROOT / "apps" / "keeper" / "infra" / "deploy" / "policy_matrix.py"
_INSTALLER = TREE_ROOT / "apps" / "keeper" / "infra" / "deploy" / "install.sh"

_SUBJECTS_DEFAULT = re.compile(r'^SUBJECTS="\$\{SUBJECTS:-([^}]+)\}"', re.M)

_ROLES = frozenset({"thinker", "viewer", "admin"})


def _registered() -> frozenset[str]:
    """The beamlines the tree has, which is the directories holding a register."""
    return frozenset(
        path.name for path in _BEAMLINES.iterdir() if (path / "devices.toml").is_file()
    )


def _matrix() -> Any:
    """Load the policy matrix, which ships beside a deployment rather than as a module."""
    spec = importlib.util.spec_from_file_location("_policy_matrix_under_test", _MATRIX)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _installer_subjects() -> tuple[str, ...]:
    found = _SUBJECTS_DEFAULT.search(_INSTALLER.read_text())
    assert found is not None, (
        "could not find the SUBJECTS default in install.sh. The line it looks "
        'for is SUBJECTS="${SUBJECTS:-<names>}", and if that spelling changed '
        "this check stopped comparing anything rather than started failing."
    )
    return tuple(found.group(1).split())


def test_the_tree_has_the_beamlines_this_check_can_find() -> None:
    """A guard on the enumerator, not on the lists.

    Every assertion below compares something against `_registered()`, so an
    enumerator returning nothing would make all of them pass against an
    empty set.
    """
    assert len(_registered()) >= 4


def test_a_beamline_name_begins_with_its_sector_and_a_role_name_does_not() -> None:
    assert all(name[0].isdigit() for name in _registered())
    assert not any(role[0].isdigit() for role in _ROLES)


def test_the_policy_matrix_names_every_beamline_the_tree_has() -> None:
    assert set(_matrix().BEAMLINES) == set(_registered())


def test_the_policy_matrix_fences_subjects_that_are_beamlines_or_known_roles() -> None:
    assert set(_matrix().SUBJECTS) == set(_registered()) | _ROLES


def test_the_installer_mints_a_token_for_every_beamline_the_tree_has() -> None:
    minted = _installer_subjects()
    assert {name for name in minted if name[0].isdigit()} == set(_registered())


def test_the_installer_and_the_policy_matrix_name_the_same_subjects() -> None:
    """The two halves of the bootstrap, which fail apart in opposite ways.

    A subject the installer mints and the matrix does not grant to holds a
    token that authorizes nothing. One the matrix grants to and the
    installer does not mint for is a permission nobody can present.
    """
    assert set(_installer_subjects()) == set(_matrix().SUBJECTS)
