"""The tail names a principal by deriving the id the installer minted.

An actor carries no name in the keeper's record. Its registration holds
an id and a timestamp, deliberately, and the one read that could resolve
an id to anything else belongs to the administrator alone. So a log
reader holding the viewer's token cannot ask who did something.

`tools/cora_tail.py` answers it anyway, by running the installer's own
derivation backwards: each actor id is a UUID5 of the subject name under
a fixed namespace, so computing the ids for the known subjects turns the
principal on an event into a word with no request at all.

That costs a copy of both halves, the namespace and the subject list,
and the copies live in a different project from the originals. Each
project's suite scans only itself, per the mirror rule, so neither the
keeper's tier nor the tail's own test can see both sides. This is the
only check that does.

## What breaks without it, and how quietly

A subject added to the installer and not here prints as eight hex
characters instead of a name, on every row that principal wrote. A
changed namespace does the same to every row at once. Neither fails,
neither logs, and both look exactly like a deployment that has not been
used much yet.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

TREE_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = TREE_ROOT / "tools" / "cora_tail.py"
_INSTALLER = TREE_ROOT / "apps" / "keeper" / "infra" / "deploy" / "install.sh"
_TOKENS = TREE_ROOT / "apps" / "keeper" / "infra" / "deploy" / "issue_tokens.py"

_SUBJECTS_DEFAULT = re.compile(r'^SUBJECTS="\$\{SUBJECTS:-([^}]+)\}"', re.M)
_NAMESPACE_URL = re.compile(r"uuid5\(NAMESPACE_URL,\s*\"([^\"]+)\"\)")


def _tail() -> Any:
    """Load the tail, which ships as a file to copy rather than a module."""
    spec = importlib.util.spec_from_file_location("_cora_tail_names_under_test", _SCRIPT)
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


def _minting_namespace() -> str:
    found = _NAMESPACE_URL.search(_TOKENS.read_text())
    assert found is not None, (
        "could not find the actor namespace in issue_tokens.py. It is the "
        "string passed to uuid5(NAMESPACE_URL, ...), and if that call moved "
        "this check stopped comparing anything."
    )
    return found.group(1)


def test_the_tail_knows_every_subject_the_installer_mints_a_token_for() -> None:
    assert set(_tail().SUBJECTS) == set(_installer_subjects())


def test_the_tail_derives_the_same_actor_ids_the_installer_does() -> None:
    """The whole derivation, not just the two literals it is built from.

    Comparing the lists alone would pass while the namespace differed,
    and comparing the namespaces alone would pass while a subject was
    missing. The map is what the tail actually looks names up in.
    """
    namespace = uuid5(NAMESPACE_URL, _minting_namespace())
    expected = {str(uuid5(namespace, subject)): subject for subject in _installer_subjects()}
    derived = _tail()._BY_ACTOR_ID
    assert derived == expected
