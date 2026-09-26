"""The baseline crawl list is data, so it is checked like code. No network."""

from __future__ import annotations

import pytest

from advisor.market import BASELINE_SOURCES, BaselineSource
from advisor.market.crawling.adapters import BY_NAME
from advisor.market.crawling.discovery import board_from_url


@pytest.mark.parametrize("source", BASELINE_SOURCES, ids=lambda s: s.company_name)
def test_every_entry_is_a_board_one_of_our_adapters_reads(source: BaselineSource) -> None:
    """A typo in an endpoint would crawl nothing, silently, every week."""
    ref = board_from_url(source.endpoint)
    assert ref is not None, f"{source.endpoint} is not a supported board"
    assert ref.adapter_name == source.kind
    assert BY_NAME[source.kind].endpoint_for(ref.slug) == source.endpoint


def test_no_endpoint_is_listed_twice() -> None:
    endpoints = [s.endpoint for s in BASELINE_SOURCES]
    assert len(endpoints) == len(set(endpoints))


def test_the_list_stays_short() -> None:
    """The platform pays to crawl and cluster every entry, for every user
    without markets — growing it is a decision, not a drive-by edit."""
    assert 0 < len(BASELINE_SOURCES) <= 20
