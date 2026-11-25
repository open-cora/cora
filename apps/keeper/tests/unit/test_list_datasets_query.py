"""The listing's address filter, paired from the two halves a surface receives.

Both surfaces take the scheme and the prefix separately, so half a filter
is a shape either can produce. The pairing and the refusal happen once, in
the query's builder, and these are its four cases.
"""

from uuid import uuid4

import pytest

from keeper.custody.aggregates.dataset import InvalidDatasetFilterError
from keeper.custody.features.list_datasets.query import ListDatasets
from keeper.shared.identifier import Identifier

pytestmark = pytest.mark.unit


def test_both_halves_of_an_address_filter_become_one_reference() -> None:
    step_id = uuid4()

    query = ListDatasets.with_address_prefix(
        scheme="place", prefix="alcf:results/", step_id=step_id
    )

    assert query.address_prefix == Identifier(scheme="place", value="alcf:results/")
    assert query.step_id == step_id


def test_neither_half_leaves_the_listing_unfiltered_by_address() -> None:
    assert ListDatasets.with_address_prefix(scheme=None, prefix=None).address_prefix is None


def test_a_scheme_without_a_prefix_is_refused() -> None:
    with pytest.raises(InvalidDatasetFilterError, match="prefix is missing"):
        ListDatasets.with_address_prefix(scheme="place", prefix=None)


def test_a_prefix_without_a_scheme_is_refused() -> None:
    with pytest.raises(InvalidDatasetFilterError, match="scheme is missing"):
        ListDatasets.with_address_prefix(scheme=None, prefix="alcf:results/")
