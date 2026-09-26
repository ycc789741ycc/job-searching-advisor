"""Evidence: one cited fact about the user's work.

Evidence is what makes a skill score explainable and what lets a resume bullet
be traced to real work. It is the main guard against the model inventing
claims, so the rules here are enforced on every AI output that cites an id
(domain section 2.3).

``CareerProfile`` holds facts only. It never holds a score.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class EvidenceSource(StrEnum):
    GITHUB = "github"
    JIRA = "jira"
    RESUME = "resume"
    # A user's answer to a follow-up question, stored as self-reported evidence.
    SELF_REPORTED = "self_reported"


@dataclass(slots=True)
class Evidence:
    """One cited fact. ``reference`` is where a human can go and check it.

    ``external_ref`` identifies the fact at its source, so re-syncing a source
    restates a fact rather than duplicating it.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    source: EvidenceSource
    external_ref: str
    reference: str
    fact: str
    observed_on: date | None
    confidence: float
    source_connection_id: uuid.UUID | None = None
    resume_file_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_confidence(self.confidence)

    @classmethod
    def cited(
        cls,
        *,
        owner_id: uuid.UUID,
        source: EvidenceSource,
        external_ref: str,
        reference: str,
        fact: str,
        observed_on: date | None,
        confidence: float,
        source_connection_id: uuid.UUID | None = None,
        resume_file_id: uuid.UUID | None = None,
    ) -> Evidence:
        return cls(
            id=uuid.uuid4(),
            owner_id=owner_id,
            source=source,
            external_ref=external_ref,
            reference=reference,
            fact=fact,
            observed_on=observed_on,
            confidence=confidence,
            source_connection_id=source_connection_id,
            resume_file_id=resume_file_id,
        )

    def restate(
        self, *, reference: str, fact: str, observed_on: date | None, confidence: float
    ) -> None:
        """A re-sync brings the fact up to date; where it came from stays."""
        _check_confidence(confidence)
        self.reference = reference
        self.fact = fact
        self.observed_on = observed_on
        self.confidence = confidence


def _check_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
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
