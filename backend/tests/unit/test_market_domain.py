"""Dedup keys, expiry and salary bands. Pure — no crawler, no database."""

from __future__ import annotations

from datetime import date

import pytest

from modules.market.domain import (
    NormalizedPosting,
    SalaryRange,
    SourceKind,
    band_from,
    canonical_key,
    expired_keys,
    normalize_title,
)


def key(company: str, title: str, location: str | None) -> str:
    return canonical_key(company=company, title=title, location=location)


def test_the_same_job_from_two_sources_collapses_to_one_key() -> None:
    board = key("Northwind Pay", "Senior Backend Engineer", "Berlin")
    career_page = key("northwind pay", "Senior  Backend  Engineer", "berlin")
    assert board == career_page


def test_gender_and_arrangement_decoration_does_not_split_a_job() -> None:
    assert key("Acme", "Senior Backend Engineer (m/f/d)", "Berlin") == key(
        "Acme", "Senior Backend Engineer", "Berlin"
    )
    assert key("Acme", "Backend Engineer (Remote)", "Berlin") == key(
        "Acme", "Backend Engineer", "Berlin"
    )


def test_accents_and_punctuation_do_not_split_a_job() -> None:
    assert key("Café Co", "Ingénieur Back-End", "Zürich") == key(
        "Cafe Co", "Ingenieur Back End", "Zurich"
    )


def test_genuinely_different_jobs_keep_different_keys() -> None:
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Acme", "Staff Backend Engineer", "Berlin"
    )
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Acme", "Senior Backend Engineer", "Munich"
    )
    assert key("Acme", "Senior Backend Engineer", "Berlin") != key(
        "Globex", "Senior Backend Engineer", "Berlin"
    )


def test_a_missing_location_is_still_a_stable_key() -> None:
    assert key("Acme", "Engineer", None) == key("Acme", "Engineer", None)
    assert key("Acme", "Engineer", None) != key("Acme", "Engineer", "Berlin")


def test_title_normalisation_keeps_meaningful_words() -> None:
    assert normalize_title("Senior Backend Engineer (m/f/d)") == "senior backend engineer"


def test_postings_missing_from_a_crawl_are_expired_not_deleted() -> None:
    known_open = {"a", "b", "c"}
    assert expired_keys(seen_now={"a", "c"}, known_open=known_open) == {"b"}


def test_a_crawl_that_sees_everything_expires_nothing() -> None:
    assert expired_keys(seen_now={"a", "b"}, known_open={"a", "b"}) == set()


def test_a_new_posting_does_not_expire_anything() -> None:
    assert expired_keys(seen_now={"a", "b", "new"}, known_open={"a", "b"}) == set()


def test_a_salary_range_cannot_be_inverted() -> None:
    with pytest.raises(ValueError, match="cannot start above"):
        SalaryRange(min_amount=200, max_amount=100, currency="EUR")


def test_a_band_needs_at_least_one_posting_with_pay() -> None:
    assert band_from([]) is None


def test_a_thin_band_is_still_shown_but_flagged() -> None:
    """A role is never hidden from the map just because the market is thin."""
    band = band_from([(80_000, 100_000, "EUR"), (90_000, 110_000, "EUR")])
    assert band is not None
    assert not band.is_confident
    assert band.currency == "EUR"


def test_a_well_sampled_band_is_confident() -> None:
    ranges = [(80_000 + i * 1_000, 100_000 + i * 1_000, "EUR") for i in range(6)]
    band = band_from(ranges)
    assert band is not None and band.is_confident
    assert band.low <= band.mid <= band.high


def test_a_band_ignores_postings_in_another_currency() -> None:
    band = band_from([(80_000, 100_000, "EUR"), (200_000, 240_000, "USD")])
    assert band is not None
    assert band.currency == "EUR" and band.sample_size == 1


def test_embedding_text_leads_with_the_title() -> None:
    posting = NormalizedPosting(
        external_id="1",
        company_name="Acme",
        title="Senior Backend Engineer",
        location="Berlin",
        description="You will build services.",
        url="https://acme.test/jobs/1",
        source_kind=SourceKind.ATS_BOARD,
        posted_on=date(2026, 9, 1),
        salary=None,
    )
    assert posting.embedding_text.startswith("Senior Backend Engineer")
    assert "You will build services." in posting.embedding_text
