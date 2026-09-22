"""Normalising job postings, and the key that deduplicates them.

The same opening turns up from several sources — a company's Greenhouse board
and its own career page carrying JSON-LD. ``canonical_key`` is what collapses
those into one posting (domain section 2.5).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

_WHITESPACE = re.compile(r"\s+")
_NOISE = re.compile(r"[^a-z0-9 ]+")

# Decoration that carries no information about which job this is. Stripped so
# "Senior Backend Engineer (m/f/d)" and "Senior Backend Engineer" are one job.
_TITLE_NOISE = (
    r"\(m/f/d\)",
    r"\(m/w/d\)",
    r"\(f/m/d\)",
    r"\(all genders\)",
    r"\(remote\)",
    r"\(hybrid\)",
    r"\(onsite\)",
    r"\(full[- ]time\)",
    r"\(part[- ]time\)",
    r"\(contract\)",
    r"\(intern\)",
)
_TITLE_NOISE_RE = re.compile("|".join(_TITLE_NOISE), re.IGNORECASE)


class PostingStatus(StrEnum):
    OPEN = "open"
    EXPIRED = "expired"


class Visibility(StrEnum):
    """Crawled postings are shared; pasted JDs belong to one user."""

    SHARED = "shared"
    PRIVATE = "private"


class SourceKind(StrEnum):
    ATS_BOARD = "atsBoard"
    JSON_LD = "jsonLd"
    PUBLIC_API = "publicApi"
    PASTED = "pasted"


class Coverage(StrEnum):
    """Whether a watched company can be crawled at all (domain decision 13)."""

    CRAWLED = "crawled"
    MANUAL = "manual"


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _WHITESPACE.sub(" ", _NOISE.sub(" ", folded.lower())).strip()


def normalize_title(title: str) -> str:
    return normalize(_TITLE_NOISE_RE.sub(" ", title))


def canonical_key(*, company: str, title: str, location: str | None) -> str:
    """company + normalized title + location, as the domain doc specifies."""
    return "|".join(
        (normalize(company), normalize_title(title), normalize(location or "unspecified"))
    )


@dataclass(frozen=True, slots=True)
class SalaryRange:
    min_amount: int
    max_amount: int
    currency: str

    def __post_init__(self) -> None:
        if self.min_amount > self.max_amount:
            raise ValueError("a salary range cannot start above its maximum")


@dataclass(frozen=True, slots=True)
class NormalizedPosting:
    """What every crawler adapter produces, whatever it parsed."""

    external_id: str
    company_name: str
    title: str
    location: str | None
    description: str
    url: str
    source_kind: SourceKind
    posted_on: date | None
    salary: SalaryRange | None

    @property
    def canonical_key(self) -> str:
        return canonical_key(company=self.company_name, title=self.title, location=self.location)

    @property
    def embedding_text(self) -> str:
        """What gets embedded: title carries most of the signal, so it leads."""
        parts = [self.title, self.title, self.location or "", self.description]
        return "\n".join(part for part in parts if part).strip()


def expired_keys(seen_now: set[str], known_open: set[str]) -> set[str]:
    """Postings missing from a crawl are expired, never deleted.

    They still count toward salary-band history; they just drop out of the jobs
    list and the opening counts.
    """
    return known_open - seen_now
