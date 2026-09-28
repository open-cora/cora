"""The page that settles how two clients name one run must say one thing.

`client-contract.md` is the agreement between the keeper and the two
programs that talk to it about the same work: which run is which, which
two metadata keys carry the join, and what the join is not. It is prose
duplicated into each of them rather than a package, because a third
project existing to hold a string and four HTTP rules would cost more
than the duplication saves.

The page asserts the property itself, in its own second paragraph: it
exists in all three projects, word for word. Nothing checked that, and it
stopped being true. A rename swept the keeper's copy alone and left the
other two behind, so the three copies disagreed about what the engine's
metadata key is called, and the sentence claiming they agreed was in all
three of them.

That is the failure this file exists to make loud, and it is the same
argument `test_the_shared_root_files_are_identical` makes about the
licence: duplication is tolerable exactly when a test proves the copies
identical, and is drift the moment nothing does.

## Why the thinker is not here

It carries a page of that name and a different page. A thinker never
speaks to an engine, so it is not party to the agreement about engine
metadata at all; its page answers what one client asks of the keeper and
says in its own words that it holds no copy of the other. Comparing it
would be comparing two answers to two questions.

The exclusion is checked rather than assumed, because the interesting way
for it to go wrong is for somebody to make that page a copy of this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

BOUND_BY_THE_CONTRACT: tuple[tuple[str, str], ...] = (
    ("keeper", "apps/keeper/docs/reference/client-contract.md"),
    ("conductor", "apps/conductor/docs/client-contract.md"),
    ("reporter", "apps/reporter/docs/client-contract.md"),
)
"""Each project the agreement binds, and where its copy sits.

The keeper's is under `reference/` and the clients' are at the top of
their sites, which is a difference in where each site puts it rather than
in what it says.
"""

THE_THINKER_PAGE = "apps/thinker/docs/client-contract.md"
"""A page of the same name answering a different question, on purpose."""


def _copy(relative: str) -> Path:
    return TREE_ROOT / relative


def test_the_contract_binds_more_than_one_project() -> None:
    """Guard the enumeration: one entry would compare a file with itself."""
    assert len(BOUND_BY_THE_CONTRACT) > 1, (
        "A contract between projects needs at least two copies to compare."
    )


@pytest.mark.parametrize(("project", "relative"), BOUND_BY_THE_CONTRACT)
def test_a_project_bound_by_the_contract_carries_its_copy(project: str, relative: str) -> None:
    """A project shipping without it ships without the agreement.

    Checked before the contents are compared, because a missing file and a
    changed one need different fixes and reading one would raise while
    naming neither.
    """
    assert _copy(relative).is_file(), (
        f"{project} carries no {relative}. Each project becomes a repository "
        "of its own, and one without this page ships without the agreement."
    )


def test_every_copy_of_the_contract_is_byte_identical() -> None:
    contents = {
        project: _copy(relative).read_bytes() for project, relative in BOUND_BY_THE_CONTRACT
    }
    assert len(set(contents.values())) == 1, (
        "client-contract.md differs between projects: "
        f"{ {p: len(v) for p, v in contents.items()} }.\n"
        "The page says in its own words that it exists in all three, word "
        "for word, so a copy that drifted makes the page wrong about itself. "
        "Copy the intended version across. If it now has to say something "
        "different per project, that sentence has to go first."
    )


def test_the_thinker_carries_a_page_of_its_own_rather_than_a_copy() -> None:
    """The exclusion above is a claim, and this is what backs it.

    A thinker is not party to the engine-metadata agreement, so its page
    of that name answers a different question. If somebody makes it a
    copy of this one, the right move is to add it to the enumeration
    rather than to keep an exclusion that no longer describes anything.
    """
    thinker = _copy(THE_THINKER_PAGE)
    assert thinker.is_file(), f"{THE_THINKER_PAGE} is missing."
    bound = {_copy(relative).read_bytes() for _, relative in BOUND_BY_THE_CONTRACT}
    assert thinker.read_bytes() not in bound, (
        f"{THE_THINKER_PAGE} is now byte-identical to the contract the other "
        "projects share. Either it has become party to that agreement, in "
        "which case add it to BOUND_BY_THE_CONTRACT, or it was overwritten."
    )
