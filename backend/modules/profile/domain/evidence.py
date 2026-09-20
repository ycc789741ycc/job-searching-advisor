"""Evidence: one cited fact about the user's work.

Evidence is what makes a skill score explainable and what lets a resume bullet
be traced to real work. It is the main guard against the model inventing
claims, so the rules here are enforced on every AI output that cites an id
(domain section 2.3).

``CareerProfile`` holds facts only. It never holds a score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class EvidenceSource(StrEnum):
    GITHUB = "github"
    JIRA = "jira"
    RESUME = "resume"
    # A user's answer to a follow-up question, stored as self-reported evidence.
    SELF_REPORTED = "self_reported"


@dataclass(frozen=True, slots=True)
class Evidence:
    """``reference`` is where a human can go and check the fact."""

    id: str
    source: EvidenceSource
    reference: str
    fact: str
    observed_at: date | None
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("evidence confidence must be between 0 and 1")


class CitationError(Exception):
    """The model cited evidence that is not in this user's profile."""

    def __init__(self, invented: frozenset[str]) -> None:
        super().__init__(f"output cites evidence that does not exist: {sorted(invented)}")
        self.invented = invented


def assert_citations_exist(cited: set[str], owned: set[str]) -> None:
    """Reject AI output that cites evidence the user does not have.

    This is checked against *this user's* evidence, so a prompt-injected id
    from a crawled page or an uploaded file cannot smuggle a claim in, and the
    model cannot decorate a resume with work that never happened.
    """
    invented = cited - owned
    if invented:
        raise CitationError(frozenset(invented))
