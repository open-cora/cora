"""Every name a profile under `infra/` imports from this package, against what the package defines.

A profile is imported by the entrypoint on a host and by nothing in this
suite, because each one imports a service library the suite does not
need. So a rename inside the package can leave a profile importing a
module or a name that no longer exists while every lane stays green, and
the first to notice is a conductor that will not start. That happened
when the compute adapter's module was renamed: only a type checker run by
hand on the profile caught it.

The profiles are read rather than imported. Each import from `conductor`
is resolved against the package itself, which imports nothing a test
cannot load.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _infra_modules() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "infra/*.py", "infra/**/*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted({ROOT / name for name in listed})


def _package_imports(module: Path) -> list[tuple[str, str]]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return [
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.split(".")[0] == "conductor"
        for alias in node.names
    ]


PROFILES = [module for module in _infra_modules() if _package_imports(module)]


def test_the_profiles_that_import_the_package_are_the_two_shipped() -> None:
    """The guard on the check below, which passes over nothing if this finds nothing."""
    assert [module.name for module in PROFILES] == ["reconstructions.py", "transfers.py"]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda module: module.name)
def test_every_name_a_profile_imports_from_the_package_exists(profile: Path) -> None:
    missing: list[str] = []
    for module_name, name in _package_imports(profile):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            missing.append(f"{module_name}, which is not a module")
            continue
        if not hasattr(module, name):
            missing.append(f"{name} from {module_name}, which does not define it")
    assert not missing, f"{profile.relative_to(ROOT)} imports " + "; ".join(missing)
