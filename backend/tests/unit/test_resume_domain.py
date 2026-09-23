"""Résumé content rules, requirement coverage, and export rendering."""

from __future__ import annotations

import pytest

from domain.resume import (
    Bullet,
    Options,
    Origin,
    Position,
    ResumeContent,
    ResumeError,
    Template,
    Verdict,
    assert_well_formed,
    assert_written_lines_cited,
    coverage,
    mark_edits,
    settle_revision,
)
from modules.resume.infra.render import render_html, render_pdf


def content(*bullets: Bullet, name: str = "Maya Lin Chen") -> ResumeContent:
    return ResumeContent(
        name=name,
        headline="Backend Engineer",
        contact="maya@example.com",
        summary="Builds payment systems.",
        experience=(Position("Backend Engineer", "Kestrel", "2022 — now", bullets),),
        skills=("Go", "Postgres"),
    )


CITED = Bullet("Owned the retry layer for payments-svc", ("e1",))


# -- the rules ------------------------------------------------------------


def test_content_survives_being_stored() -> None:
    original = content(CITED, Bullet("My own line", (), Origin.YOURS, answers="Lead"))
    assert ResumeContent.from_dict(original.to_dict()) == original


def test_a_written_line_must_cite_evidence() -> None:
    with pytest.raises(ResumeError, match="cites no evidence"):
        assert_written_lines_cited(content(CITED, Bullet("Led everything")))


def test_a_line_the_user_wrote_may_stand_uncited() -> None:
    assert_written_lines_cited(content(CITED, Bullet("Led the guild", (), Origin.YOURS)))


def test_a_resume_needs_a_name_and_no_empty_lines() -> None:
    with pytest.raises(ResumeError, match="name"):
        assert_well_formed(content(CITED, name=" "))
    with pytest.raises(ResumeError, match="empty line"):
        assert_well_formed(content(Bullet("  ", ("e1",))))


def test_an_edited_line_becomes_the_users_and_an_untouched_one_keeps_its_source() -> None:
    before = content(CITED, Bullet("Cut p99 latency by 40%", ("e2",)))
    edited = content(CITED, Bullet("Cut p99 latency by 40% across checkout", ("e2",)))

    settled = mark_edits(before, edited)

    kept, changed = settled.experience[0].bullets
    assert kept == CITED
    assert changed.origin is Origin.YOURS
    assert changed.evidence_ids == ("e2",)


def test_a_proposal_cannot_relabel_the_users_own_line() -> None:
    mine = Bullet("Ran the incident guild", (), Origin.YOURS)
    proposed = content(
        Bullet(mine.text, ("e9",), Origin.WRITTEN),
        Bullet("Answered their top requirement first", ("e1",), Origin.YOURS),
    )

    settled = settle_revision(content(mine), proposed)

    kept, new = settled.experience[0].bullets
    assert kept == mine, "an unchanged line is the line it was"
    assert new.origin is Origin.WRITTEN, "new text is the model's, whatever it claims"


# -- coverage -------------------------------------------------------------


def test_coverage_is_decided_by_score_against_the_bar() -> None:
    rows = coverage(
        requirements=["Leads", "Reliable", "Mentors", "Kubernetes", "Unscored"],
        requirement_map={
            "Leads": "lead",
            "Reliable": "rel",
            "Mentors": "mentor",
            "Kubernetes": None,
            "Unscored": "craft",
        },
        scores={"lead": 70, "rel": 75, "mentor": 50, "craft": 90},
        targets={"lead": 83, "rel": 60, "mentor": 80},
        evidence={"lead": ["e1"], "rel": ["e2"]},
    )
    assert [(r.requirement, r.verdict) for r in rows] == [
        ("Leads", Verdict.PARTIAL),  # 13 short: within 14
        ("Reliable", Verdict.COVERED),
        ("Mentors", Verdict.GAP),
        ("Kubernetes", Verdict.GAP),  # maps to nothing: no evidence at all
        ("Unscored", Verdict.GAP),  # the Target sets no bar for it
    ]
    assert rows[1].evidence_ids == ("e2",)
    assert rows[3].evidence_ids == ()


def test_fourteen_short_is_no_longer_partial() -> None:
    [row] = coverage(
        requirements=["Leads"],
        requirement_map={"Leads": "lead"},
        scores={"lead": 66},
        targets={"lead": 80},
        evidence={},
    )
    assert row.verdict is Verdict.GAP


# -- export ---------------------------------------------------------------


def test_every_value_is_escaped_in_the_export() -> None:
    hostile = content(Bullet('<script>alert("x")</script>', ("e1",)), name="<b>Maya</b>")
    html = render_html(hostile, template=Template.WARM, options=Options())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>Maya</b>" not in html


def test_trim_keeps_three_lines_a_role() -> None:
    long = content(*(Bullet(f"Line {i}", ("e1",)) for i in range(6)))
    html = render_html(long, template=Template.PLAIN, options=Options(trim=True))
    assert "Line 2" in html
    assert "Line 3" not in html


def test_each_template_has_its_own_rule() -> None:
    warm = render_html(content(CITED), template=Template.WARM, options=Options())
    brief = render_html(content(CITED), template=Template.BRIEF, options=Options())
    assert "#c67139" in warm
    assert "#7a8a5e" in brief


def test_the_export_is_a_pdf_rendered_without_fetching_anything() -> None:
    pdf = render_pdf(render_html(content(CITED), template=Template.WARM, options=Options()))
    assert pdf.startswith(b"%PDF-")


def test_an_export_that_tries_to_fetch_something_is_refused() -> None:
    # render_html never emits a URL; this is the guard behind that.
    with pytest.raises(ValueError, match="does not fetch"):
        render_pdf('<img src="http://169.254.169.254/latest/meta-data">')
