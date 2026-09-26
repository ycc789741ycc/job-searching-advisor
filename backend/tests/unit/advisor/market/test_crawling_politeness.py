"""Rate limiting, robots.txt and slug guessing. No network."""

from __future__ import annotations

import pytest

from advisor.market._crawling.discovery import (
    BoardRef,
    board_from_url,
    candidate_slugs,
    discover_board,
)
from advisor.market._crawling.politeness import RateLimiter, RobotsCache, origin_of, robots_url_for
from kernel.errors import UpstreamFailedError


def test_no_robots_file_means_nothing_is_disallowed() -> None:
    robots = RobotsCache("TestBot/1.0")
    robots.remember("https://acme.test", None)
    assert robots.allows("https://acme.test/anything")


def test_a_disallowed_path_is_refused() -> None:
    robots = RobotsCache("TestBot/1.0")
    robots.remember("https://acme.test", "User-agent: *\nDisallow: /jobs\n")
    assert not robots.allows("https://acme.test/jobs/1")
    assert robots.allows("https://acme.test/about")


def test_a_rule_aimed_at_our_agent_is_honoured() -> None:
    robots = RobotsCache("JobSearchingAdvisorBot")
    robots.remember(
        "https://acme.test",
        "User-agent: JobSearchingAdvisorBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n",
    )
    assert not robots.allows("https://acme.test/jobs")


def test_a_host_is_only_looked_up_once_per_run() -> None:
    robots = RobotsCache("TestBot/1.0")
    assert not robots.knows("https://acme.test")
    robots.remember("https://acme.test", None)
    assert robots.knows("https://acme.test")


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://acme.test/jobs/1?x=2", "https://acme.test"),
        ("http://acme.test:8080/a", "http://acme.test:8080"),
    ],
)
def test_origin_ignores_path_and_query(url: str, origin: str) -> None:
    assert origin_of(url) == origin
    assert robots_url_for(url) == f"{origin}/robots.txt"


async def test_the_rate_limiter_spaces_calls_to_one_host() -> None:
    import time

    limiter = RateLimiter(per_second=50)
    start = time.monotonic()
    await limiter.wait("https://acme.test/a")
    await limiter.wait("https://acme.test/b")
    assert time.monotonic() - start >= 0.02


async def test_different_hosts_do_not_block_each_other() -> None:
    import time

    limiter = RateLimiter(per_second=2)
    start = time.monotonic()
    await limiter.wait("https://one.test/a")
    await limiter.wait("https://two.test/a")
    assert time.monotonic() - start < 0.4


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        ("Northwind Pay", ["northwindpay", "northwind-pay"]),
        ("Acme", ["acme"]),
        ("Meridian Labs, Inc.", ["meridianlabsinc", "meridian-labs-inc"]),
    ],
)
def test_slug_candidates_cover_the_usual_board_naming(company: str, expected: list[str]) -> None:
    assert candidate_slugs(company) == expected


class StubClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    async def get_json(self, url: str, **_: object) -> object:
        self.requested.append(url)
        if url not in self.responses:
            raise UpstreamFailedError("not found", url=url)
        return self.responses[url]


class StubAdapter:
    name = "stub"

    def __init__(self, url: str) -> None:
        self._url = url

    def endpoint_for(self, slug: str) -> str:
        return f"{self._url}/{slug}"

    def parse(self, payload: object, *, company_name: str) -> list[object]:
        return list(payload) if isinstance(payload, list) else []


async def test_discovery_returns_the_first_board_that_has_postings() -> None:
    adapter = StubAdapter("https://board.test")
    client = StubClient({"https://board.test/acme": [{"a": 1}, {"b": 2}]})
    found = await discover_board(client, "Acme", adapters=(adapter,))  # type: ignore[arg-type]
    assert found is not None
    assert found.adapter_name == "stub" and found.posting_count == 2


async def test_a_company_with_no_supported_board_falls_back_to_manual() -> None:
    """None here is what makes a subscription `manual`."""
    adapter = StubAdapter("https://board.test")
    client = StubClient({})
    assert await discover_board(client, "Uncrawlable Ltd", adapters=(adapter,)) is None  # type: ignore[arg-type]


async def test_a_board_that_exists_but_is_empty_is_not_treated_as_found() -> None:
    adapter = StubAdapter("https://board.test")
    client = StubClient({"https://board.test/acme": []})
    assert await discover_board(client, "Acme", adapters=(adapter,)) is None  # type: ignore[arg-type]


# -- a link the user gave ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/northwind", BoardRef("greenhouse", "northwind")),
        (
            "https://job-boards.greenhouse.io/northwind/jobs/123",
            BoardRef("greenhouse", "northwind"),
        ),
        (
            "https://boards-api.greenhouse.io/v1/boards/northwind/jobs",
            BoardRef("greenhouse", "northwind"),
        ),
        ("https://jobs.lever.co/kestrel/abc-123", BoardRef("lever", "kestrel")),
        ("https://api.lever.co/v0/postings/kestrel?mode=json", BoardRef("lever", "kestrel")),
        ("https://jobs.ashbyhq.com/meridian.labs", BoardRef("ashby", "meridian.labs")),
        (
            "https://api.ashbyhq.com/posting-api/job-board/meridian",
            BoardRef("ashby", "meridian"),
        ),
        ("HTTPS://JOBS.LEVER.CO/Kestrel", BoardRef("lever", "Kestrel")),
    ],
)
def test_a_board_url_names_its_board_without_a_request(url: str, expected: BoardRef) -> None:
    assert board_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://meridianlabs.io/careers",  # a careers page: maybe JSON-LD, not a board
        "https://boards.greenhouse.io/",  # no slug
        "https://jobs.eu.lever.co/kestrel",  # regional API lives elsewhere
        "https://evil.test/boards.greenhouse.io/northwind",  # host, not path, decides
        "ftp://jobs.lever.co/kestrel",
        "not a url",
    ],
)
def test_anything_else_is_not_read_as_a_board(url: str) -> None:
    assert board_from_url(url) is None


async def test_a_board_url_is_tried_before_guessing_from_the_name() -> None:
    """The user's link names a slug no guess would reach."""
    from advisor.market._crawling.adapters import BY_NAME

    endpoint = BY_NAME["lever"].endpoint_for("kestrel-fin-eng")
    client = StubClient({endpoint: [{"text": "Senior Backend Engineer", "hostedUrl": "x"}]})
    found = await discover_board(
        client,  # type: ignore[arg-type]
        "Kestrel Financial",
        url="https://jobs.lever.co/kestrel-fin-eng",
        adapters=(),
    )
    assert found is not None
    assert (found.adapter_name, found.endpoint) == ("lever", endpoint)
    assert client.requested == [endpoint]


async def test_an_empty_board_behind_a_link_falls_back_to_guessing() -> None:
    adapter = StubAdapter("https://board.test")
    client = StubClient({"https://board.test/acme": [{"a": 1}]})
    found = await discover_board(
        client,  # type: ignore[arg-type]
        "Acme",
        url="https://jobs.lever.co/acme-old",
        adapters=(adapter,),  # type: ignore[arg-type]
    )
    assert found is not None and found.adapter_name == "stub"


class PageClient(StubClient):
    """Also serves plain pages, for a careers URL carrying JSON-LD."""

    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        super().__init__({})
        self.pages = pages

    async def request(self, method: str, url: str, **_: object) -> object:
        self.requested.append(url)
        status, body = self.pages.get(url, (404, ""))
        return type("Response", (), {"status_code": status, "text": body})()


_JSON_LD_PAGE = """
<html><script type="application/ld+json">
{"@type": "JobPosting", "title": "Staff Platform Engineer",
 "hiringOrganization": {"name": "Meridian Labs"},
 "description": "Own the reliability roadmap."}
</script></html>
"""


async def test_a_careers_page_with_job_posting_markup_is_a_source() -> None:
    client = PageClient({"https://meridian.test/careers": (200, _JSON_LD_PAGE)})
    found = await discover_board(
        client,  # type: ignore[arg-type]
        "Meridian Labs",
        url="https://meridian.test/careers",
        adapters=(),
    )
    assert found is not None
    assert (found.adapter_name, found.endpoint, found.posting_count) == (
        "json-ld",
        "https://meridian.test/careers",
        1,
    )
    # robots.txt is read first, as the weekly crawl will.
    assert client.requested[0] == "https://meridian.test/robots.txt"


async def test_a_careers_page_robots_txt_forbids_is_not_reported_as_crawlable() -> None:
    client = PageClient(
        {
            "https://meridian.test/robots.txt": (200, "User-agent: *\nDisallow: /careers\n"),
            "https://meridian.test/careers": (200, _JSON_LD_PAGE),
        }
    )
    found = await discover_board(
        client,  # type: ignore[arg-type]
        "Meridian Labs",
        url="https://meridian.test/careers",
        adapters=(),
    )
    assert found is None
    assert "https://meridian.test/careers" not in client.requested
