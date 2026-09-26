"""Resume parsing limits and traceability."""

from __future__ import annotations

import pytest

from advisor.profile.infra.resume_parser import parse
from kernel.errors import ValidationError


def text_resume(body: str) -> bytes:
    return body.encode("utf-8")


def test_each_substantive_line_becomes_traceable_evidence() -> None:
    resume = text_resume(
        "Maya Chen\n"
        "- Owned the regional failover runbook for the payments platform.\n"
        "- Cut median cycle time from 6 days to 2.4 days across the team.\n"
    )
    parsed = parse(resume, content_type="text/plain", filename="maya.txt", max_pages=10)

    assert len(parsed.drafts) == 2
    assert parsed.drafts[0].fact.startswith("Owned the regional failover")
    assert parsed.drafts[0].reference == "Resume · maya.txt · line 2"


def test_headings_and_stray_tokens_are_not_evidence() -> None:
    parsed = parse(
        text_resume("EXPERIENCE\nSkills\nBuilt and ran the multi-region ledger service.\n"),
        content_type="text/plain",
        filename="r.txt",
        max_pages=10,
    )
    assert [d.fact for d in parsed.drafts] == ["Built and ran the multi-region ledger service."]


def test_resume_evidence_is_weaker_than_a_merged_pull_request() -> None:
    """Self-authored claims should not outweigh observed work."""
    parsed = parse(
        text_resume("- Led the payments reliability workstream end to end.\n"),
        content_type="text/plain",
        filename="r.txt",
        max_pages=10,
    )
    assert parsed.drafts[0].confidence < 0.8


def test_an_unsupported_format_is_refused() -> None:
    with pytest.raises(ValidationError, match="not a resume format"):
        parse(b"\x00\x01", content_type="image/png", filename="x.png", max_pages=10)


def test_an_empty_file_is_refused_rather_than_stored_as_nothing() -> None:
    with pytest.raises(ValidationError, match="no text could be read"):
        parse(text_resume("   \n\n"), content_type="text/plain", filename="r.txt", max_pages=10)


def test_a_corrupt_pdf_is_refused_with_a_readable_message() -> None:
    with pytest.raises(ValidationError, match="could not be opened"):
        parse(b"not a pdf at all", content_type="application/pdf", filename="r.pdf", max_pages=10)


def test_a_very_long_resume_is_truncated_rather_than_flooding_the_profile() -> None:
    body = "\n".join(f"Delivered project number {i} for the platform team." for i in range(400))
    parsed = parse(text_resume(body), content_type="text/plain", filename="r.txt", max_pages=10)
    assert len(parsed.drafts) == 120


def test_bullets_are_stripped_but_the_claim_is_kept() -> None:
    parsed = parse(
        text_resume("•  Designed the idempotency layer for payments.\n"),
        content_type="text/plain",
        filename="r.txt",
        max_pages=10,
    )
    assert parsed.drafts[0].fact == "Designed the idempotency layer for payments."
