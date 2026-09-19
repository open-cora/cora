"""A list written out in a docs page must match the constant it claims to name.

A prose list and a frozenset are two independent sides of the same fact, which
is the condition under which a check is worth writing: the docs page cannot
drift from the code without one of them being wrong, and nothing else notices
which. `conventions.md` listed four unit systems while the allowlist enforced
five, so a reader following the page would have believed a valid namespace was
rejected.

Two entries. The mechanism generalizes to any docs list that names a closed
set in code; the cost of an entry is one row below.

The second entry was added after the page and the code disagreed for a
second time, and worse than the first. `conventions.md` told an author to
close every schema with `additionalProperties: false`, which the subset
forbids outright, so the page's advice produced a 400. It also described
the keyword rule as a denylist of four when the code is an allowlist of
nine. Nothing tied the two together, which is the only reason either could
happen.
"""

import re

import pytest

from aroc.shared.json_schema.subset import ALLOWED_SCHEMA_KEYS
from aroc.shared.json_schema.validation import ALLOWED_UNIT_SYSTEMS
from tests.architecture.conftest import REPO_ROOT

pytestmark = pytest.mark.architecture

_CONVENTIONS = REPO_ROOT / "docs" / "reference" / "conventions.md"

_SCHEMA_KEYWORD_LINE = re.compile(r"^- \*\*Allowed anywhere in a schema\*\*: \(([^)]*)\)\.")
"""The bullet in the schema section that spells the allowlist out in prose.

Anchored on the whole bullet like its neighbour below, so a rewrite that
moves the list fails loudly here instead of matching nothing and passing.
"""

_UNIT_SYSTEM_LINE = re.compile(r"^- \*\*`system`\*\*: namespace identifier \(([^)]*)\)\.")
"""The bullet in the units section that spells the allowlist out in prose.

Anchored on the whole bullet rather than on the names, so a rewrite that moves
the list somewhere else fails loudly here instead of matching nothing and
passing.
"""


def test_the_conventions_page_is_readable_at_the_path_this_check_uses() -> None:
    """Guard the read, so a moved page cannot make the check below vacuous."""
    assert _CONVENTIONS.is_file(), f"No conventions page at {_CONVENTIONS}"


def test_docs_unit_systems_match_the_allowlist() -> None:
    text = _CONVENTIONS.read_text()
    matches = [_UNIT_SYSTEM_LINE.match(line) for line in text.splitlines()]
    found = [m for m in matches if m is not None]
    assert len(found) == 1, (
        "Expected exactly one `system` bullet in the units section of "
        f"conventions.md, found {len(found)}. If the bullet was reworded, "
        "update _UNIT_SYSTEM_LINE here in the same commit."
    )

    documented = set(re.findall(r"`([a-z0-9]+)`", found[0].group(1)))
    assert documented == set(ALLOWED_UNIT_SYSTEMS), (
        "The unit systems listed in docs/reference/conventions.md disagree with "
        "ALLOWED_UNIT_SYSTEMS. Documented but not allowed: "
        f"{sorted(documented - set(ALLOWED_UNIT_SYSTEMS))}. Allowed but not "
        f"documented: {sorted(set(ALLOWED_UNIT_SYSTEMS) - documented)}."
    )


def test_docs_schema_keywords_match_the_allowlist() -> None:
    """The stored subset, as the page states it and as the code enforces it.

    Backticked tokens are pulled out rather than split on commas, because
    `$schema` carries a sigil and a comma-split would also swallow the
    surrounding prose if the bullet were ever reworded mid-sentence.
    """
    text = _CONVENTIONS.read_text()
    matches = [_SCHEMA_KEYWORD_LINE.match(line) for line in text.splitlines()]
    found = [m for m in matches if m is not None]
    assert len(found) == 1, (
        "Expected exactly one allowed-keywords bullet in the schema section of "
        f"conventions.md, found {len(found)}. If the bullet was reworded, "
        "update _SCHEMA_KEYWORD_LINE here in the same commit."
    )

    documented = set(re.findall(r"`([$A-Za-z][A-Za-z0-9]*)`", found[0].group(1)))
    assert documented == set(ALLOWED_SCHEMA_KEYS), (
        "The schema keywords listed in docs/reference/conventions.md disagree "
        "with ALLOWED_SCHEMA_KEYS. Documented but not allowed: "
        f"{sorted(documented - set(ALLOWED_SCHEMA_KEYS))}. Allowed but not "
        f"documented: {sorted(set(ALLOWED_SCHEMA_KEYS) - documented)}.\n"
        "Widening the allowlist means widening the page in the same commit, "
        "and a keyword that takes a schema also means teaching check_subset "
        "to recurse into it."
    )
