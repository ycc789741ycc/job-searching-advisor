"""Adapters turn whatever a board returns into one normalised shape.

Run against saved fixtures, so these are hermetic — no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from advisor.market import SourceKind
from advisor.market._crawling.adapters import (
    AshbyAdapter,
    GreenhouseAdapter,
    JsonLdAdapter,
    LeverAdapter,
    strip_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> object:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(raw) if name.endswith(".json") else raw


# -- Greenhouse -------------------------------------------------------------


def test_greenhouse_normalises_a_posting() -> None:
    postings = GreenhouseAdapter().parse(load("greenhouse.json"), company_name="Northwind Pay")
    senior = postings[0]
    assert senior.title == "Senior Backend Engineer (m/f/d)"
    assert senior.location == "Berlin"
    assert senior.source_kind is SourceKind.ATS_BOARD
    assert senior.url.endswith("/4012")
    assert "You will own the ledger API." in senior.description
    assert "<p>" not in senior.description


def test_greenhouse_reads_the_published_pay_range() -> None:
    senior = GreenhouseAdapter().parse(load("greenhouse.json"), company_name="Northwind Pay")[0]
    assert senior.salary is not None
    assert (senior.salary.min_amount, senior.salary.max_amount) == (80_000, 105_000)
    assert senior.salary.currency == "EUR"


def test_a_posting_with_no_title_is_skipped_rather_than_stored_blank() -> None:
    postings = GreenhouseAdapter().parse(load("greenhouse.json"), company_name="Northwind Pay")
    assert [p.title for p in postings] == ["Senior Backend Engineer (m/f/d)", "Platform Engineer"]


def test_a_posting_without_pay_has_no_invented_salary() -> None:
    platform = GreenhouseAdapter().parse(load("greenhouse.json"), company_name="Northwind Pay")[1]
    assert platform.salary is None
    assert platform.location is None


def test_gender_decoration_does_not_split_the_dedup_key() -> None:
    postings = GreenhouseAdapter().parse(load("greenhouse.json"), company_name="Northwind Pay")
    assert postings[0].canonical_key == "northwind pay|senior backend engineer|berlin"


# -- Lever ------------------------------------------------------------------


def test_lever_normalises_a_posting_including_its_epoch_millis_date() -> None:
    postings = LeverAdapter().parse(load("lever.json"), company_name="Meridian Labs")
    staff = postings[0]
    assert staff.title == "Staff Platform Engineer"
    assert staff.location == "Remote EU"
    assert staff.posted_on is not None and staff.posted_on.year == 2025
    assert staff.salary is not None and staff.salary.currency == "EUR"


def test_lever_falls_back_to_the_html_description() -> None:
    dx = LeverAdapter().parse(load("lever.json"), company_name="Meridian Labs")[1]
    assert dx.description == "Make the toolchain good."


# -- Ashby ------------------------------------------------------------------


def test_ashby_picks_the_salary_component_not_the_equity_one() -> None:
    posting = AshbyAdapter().parse(load("ashby.json"), company_name="Fieldnote")[0]
    assert posting.salary is not None
    assert (posting.salary.min_amount, posting.salary.max_amount) == (75_000, 95_000)


# -- JSON-LD ----------------------------------------------------------------


def test_json_ld_is_found_inside_an_at_graph() -> None:
    postings = JsonLdAdapter().parse(load("career_page.html"), company_name="fallback")
    assert len(postings) == 1
    posting = postings[0]
    assert posting.title == "Developer Experience Lead"
    assert posting.company_name == "Halcyon"
    assert posting.location == "Berlin, BE"
    assert posting.source_kind is SourceKind.JSON_LD


def test_json_ld_unescapes_entities_and_drops_markup() -> None:
    posting = JsonLdAdapter().parse(load("career_page.html"), company_name="x")[0]
    assert posting.description == "Own the internal platform & its docs."


def test_one_malformed_json_ld_block_does_not_lose_the_page() -> None:
    """The second <script> in the fixture is deliberately broken."""
    assert len(JsonLdAdapter().parse(load("career_page.html"), company_name="x")) == 1


def test_a_page_with_no_job_markup_yields_nothing() -> None:
    assert JsonLdAdapter().parse("<html><body>no jobs</body></html>", company_name="x") == []


# -- shared helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<p>One</p><p>Two</p>", "One\nTwo"),
        ("<ul><li>A</li><li>B</li></ul>", "A\nB"),
        ("Plain &amp; simple", "Plain & simple"),
        ("", ""),
    ],
)
def test_strip_html_keeps_the_text_and_the_line_breaks(raw: str, expected: str) -> None:
    assert strip_html(raw) == expected


def test_every_adapter_builds_an_endpoint_from_a_slug() -> None:
    assert "northwind" in GreenhouseAdapter().endpoint_for("northwind")
    assert "northwind" in LeverAdapter().endpoint_for("northwind")
    assert "northwind" in AshbyAdapter().endpoint_for("northwind")


def test_an_empty_payload_is_handled_rather_than_raising() -> None:
    for adapter in (GreenhouseAdapter(), LeverAdapter(), AshbyAdapter()):
        assert adapter.parse(None, company_name="x") == []
