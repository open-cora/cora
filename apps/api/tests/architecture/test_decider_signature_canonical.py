"""Deciders share one signature shape, so a reader learns it once.

Per the decider section of docs/reference/patterns.md:

    create-style:  decide(state, command, *, now, new_id) -> list[Event]
    update-style:  decide(state, command, *, now)         -> list[Event]

The first two parameters are positional and are exactly state and
command, in that order. Cross-aggregate context, the clock, the id
generator and any slice-specific extra all sit after the keyword-only
marker, where they are named at every call site.

Two properties are pinned here:

  1. a top-level decide function exists in the module
  2. its positional parameters are exactly state and command

Return type is deliberately not pinned. A slice that writes several
streams at once returns a frozen wrapper holding one event list per
stream rather than a bare list, and the handler hands those lists to the
event store as a single atomic batch. That shape is documented at the
slice that needs it.

`WIP_DECIDERS` is an allowlist for a signature that diverges on purpose
or is mid-change. It is empty, and the drift check below keeps a stale
entry from surviving the fix that made it unnecessary.
"""

import ast
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

WIP_DECIDERS: frozenset[str] = frozenset()
"""Deciders exempted from the canonical shape, by qualified module name.

Empty. An entry must cite the reason and the change that will close it.
Adding one is a decision, not a way past the check: the drift test below
fails on an entry whose decider has since been conformed.
"""


def _decider_files() -> list[Path]:
    tracked = tracked_python_files()
    out: list[Path] = []
    for bc in discovered_bcs():
        features = AROC_ROOT / bc / "features"
        out.extend(
            sorted(
                f
                for f in tracked
                if f.stem == "decider"
                and f.parent.parent == features
                and not f.parent.name.startswith("_")
            )
        )
    return out


def _qualified(p: Path) -> str:
    return "aroc." + ".".join(p.relative_to(AROC_ROOT).with_suffix("").parts)


def _find_decide_function(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "decide":
            return node
    return None


def _positional_arg_names(func: ast.FunctionDef) -> list[str]:
    return [a.arg for a in func.args.posonlyargs] + [a.arg for a in func.args.args]


def test_the_decider_signature_scan_finds_at_least_one_decider() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _decider_files(), (
        "No decider module found under any bounded context's features/ "
        "directory, so the signature rule below ran against nothing."
    )


@pytest.mark.parametrize("decider", _decider_files(), ids=_qualified)
def test_a_decider_takes_state_and_command_positionally_and_the_rest_by_keyword(
    decider: Path,
) -> None:
    qualified = _qualified(decider)
    if qualified in WIP_DECIDERS:
        pytest.skip(f"{qualified} is allowlisted in WIP_DECIDERS")

    tree = ast.parse(decider.read_text())
    func = _find_decide_function(tree)
    assert func is not None, (
        f"{qualified}: no top-level decide function. Every command and update slice exposes one."
    )

    positional = _positional_arg_names(func)
    assert positional == ["state", "command"], (
        f"{qualified}: decide takes {positional!r} positionally, expected exactly "
        "['state', 'command']. Move the extras after the keyword-only marker, per "
        "docs/reference/patterns.md."
    )


def _stale_decider_entries(allowlist: Iterable[str], root: Path) -> list[str]:
    """Allowlist keys that no longer earn their place, with the reason.

    Takes the source root as an argument so the drift check can be run
    against a tree built for the purpose. `WIP_DECIDERS` is empty, so
    without that this function would never execute and its path
    resolution would be unverified.
    """
    stale: list[str] = []
    for qualified in sorted(allowlist):
        parts = qualified.split(".")
        if parts[0] != "aroc":
            stale.append(f"{qualified}: must start with 'aroc.'")
            continue
        path = root.joinpath(*parts[1:]).with_suffix(".py")
        if not path.is_file():
            stale.append(f"{qualified}: names a module that no longer exists.")
            continue
        func = _find_decide_function(ast.parse(path.read_text()))
        if func is None:
            stale.append(f"{qualified}: names a module whose decide function is gone.")
            continue
        positional = _positional_arg_names(func)
        if positional == ["state", "command"]:
            stale.append(
                f"{qualified}: signature is now canonical ({positional!r}), so the "
                "entry is covering nothing."
            )
    return stale


def test_no_allowlisted_decider_has_a_canonical_signature_or_has_gone_missing() -> None:
    """Drift catcher: an entry that no longer deviates is dead weight.

    Re-running the detector over the allowlist forces the entry to be removed
    in the same change that conforms the decider, rather than surviving as a
    permission nobody rechecked.
    """
    stale = _stale_decider_entries(WIP_DECIDERS, AROC_ROOT)
    assert not stale, "WIP_DECIDERS entries to prune:\n  " + "\n  ".join(stale)


def test_the_drift_catcher_reports_an_entry_that_no_longer_earns_its_place() -> None:
    """Run the catcher over entries that are stale, because none here is.

    `WIP_DECIDERS` is empty and should stay that way, so the loop above
    never executes: its path resolution, its parse and its comparison
    are all unreached. This calls the same function with entries that
    are each stale in a different way.

    The last case points at a real decider in this repository, whose
    signature IS canonical. An allowlist entry for it would be exactly
    the permission nobody rechecked.
    """
    assert _stale_decider_entries(["notaroc.somewhere.decider"], AROC_ROOT) == [
        "notaroc.somewhere.decider: must start with 'aroc.'"
    ]

    (gone,) = _stale_decider_entries(["aroc.access.features.vanished.decider"], AROC_ROOT)
    assert "no longer exists" in gone

    (conformed,) = _stale_decider_entries(
        ["aroc.access.features.register_actor.decider"], AROC_ROOT
    )
    assert "now canonical" in conformed
