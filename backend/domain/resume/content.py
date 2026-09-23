"""The résumé as structured content, and the rules it must keep (section 2.9).

A résumé is sections and bullets, never free text. Every bullet the model
writes cites the Evidence it was written from — the grey note under each line
in the prototype — and a written bullet with nothing behind it is rejected:
that is the guard against invented claims. A line the user types themselves is
theirs to word, cited or not.

What each of the Target's requirements is covered by is decided here, from the
user's scores against the Target's bar, not by the model (section 2.9:
RequirementCoverage "is computed from the Target's TargetProfile and the user's
scores").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

MAX_ROLES = 6
MAX_BULLETS_PER_ROLE = 8
MAX_SKILLS = 30
MAX_TEXT = 600

# A dimension this far below the Target's bar still counts as partly covered.
# The prototype's threshold.
PARTIAL_WITHIN = 14


class ResumeError(ValueError):
    """Content that breaks the rules; it is rejected, not repaired."""


class Origin(StrEnum):
    """Who wrote a line. Only the model's lines must cite evidence."""

    WRITTEN = "written"
    YOURS = "yours"


class VersionSource(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"
    CHAT = "chat"


class Template(StrEnum):
    """Visual layout for export: rendering only, never a domain rule."""

    WARM = "warm"
    PLAIN = "plain"
    BRIEF = "brief"


class Verdict(StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    GAP = "gap"


@dataclass(frozen=True, slots=True)
class Options:
    """How the Resume Advisor writes (the prototype's option toggles)."""

    # Quantify bullets with numbers from the evidence.
    metrics: bool = True
    # Order skills by what the Target screens for.
    reorder: bool = True
    # Fit on one page.
    trim: bool = False


@dataclass(frozen=True, slots=True)
class Bullet:
    text: str
    evidence_ids: tuple[str, ...] = ()
    origin: Origin = Origin.WRITTEN
    # Which of the Target's requirements this line answers, if any.
    answers: str | None = None


@dataclass(frozen=True, slots=True)
class Position:
    title: str
    org: str
    when: str
    bullets: tuple[Bullet, ...]


@dataclass(frozen=True, slots=True)
class ResumeContent:
    name: str
    headline: str
    contact: str
    summary: str
    experience: tuple[Position, ...]
    skills: tuple[str, ...] = field(default_factory=tuple)

    def bullets(self) -> Iterable[Bullet]:
        for position in self.experience:
            yield from position.bullets

    def cited(self) -> set[str]:
        return {i for bullet in self.bullets() for i in bullet.evidence_ids}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "headline": self.headline,
            "contact": self.contact,
            "summary": self.summary,
            "experience": [
                {
                    "title": p.title,
                    "org": p.org,
                    "when": p.when,
                    "bullets": [
                        {
                            "text": b.text,
                            "evidence_ids": list(b.evidence_ids),
                            "origin": str(b.origin),
                            "answers": b.answers,
                        }
                        for b in p.bullets
                    ],
                }
                for p in self.experience
            ],
            "skills": list(self.skills),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResumeContent:
        return cls(
            name=str(data.get("name", "")),
            headline=str(data.get("headline", "")),
            contact=str(data.get("contact", "")),
            summary=str(data.get("summary", "")),
            experience=tuple(
                Position(
                    title=str(p.get("title", "")),
                    org=str(p.get("org", "")),
                    when=str(p.get("when", "")),
                    bullets=tuple(
                        Bullet(
                            text=str(b.get("text", "")),
                            evidence_ids=tuple(str(i) for i in b.get("evidence_ids", [])),
                            origin=Origin(b.get("origin", Origin.WRITTEN)),
                            answers=b.get("answers"),
                        )
                        for b in p.get("bullets", [])
                    ),
                )
                for p in data.get("experience", [])
            ),
            skills=tuple(str(s) for s in data.get("skills", [])),
        )


def assert_well_formed(content: ResumeContent) -> None:
    if not content.name.strip():
        raise ResumeError("a résumé needs a name")
    if len(content.experience) > MAX_ROLES:
        raise ResumeError(f"at most {MAX_ROLES} roles")
    if len(content.skills) > MAX_SKILLS:
        raise ResumeError(f"at most {MAX_SKILLS} skills")
    for position in content.experience:
        if len(position.bullets) > MAX_BULLETS_PER_ROLE:
            raise ResumeError(f"at most {MAX_BULLETS_PER_ROLE} bullets under {position.title!r}")
        for bullet in position.bullets:
            if not bullet.text.strip():
                raise ResumeError(f"an empty line under {position.title!r}")
            if len(bullet.text) > MAX_TEXT:
                raise ResumeError(f"a line under {position.title!r} is too long")


def assert_written_lines_cited(content: ResumeContent) -> None:
    """Every line the model wrote cites the work it was written from."""
    for position in content.experience:
        for bullet in position.bullets:
            if bullet.origin is Origin.WRITTEN and not bullet.evidence_ids:
                raise ResumeError(
                    f"a written line under {position.title!r} cites no evidence: "
                    f"{bullet.text[:80]!r}"
                )


def mark_edits(previous: ResumeContent | None, edited: ResumeContent) -> ResumeContent:
    """A line the user changed is theirs; one left as it was keeps its origin.

    Matching is by exact text: a line that reads the same is the same line,
    wherever it moved.
    """
    before = {b.text: b for b in previous.bullets()} if previous else {}
    return replace(
        edited,
        experience=tuple(
            replace(
                position,
                bullets=tuple(
                    before[b.text] if b.text in before else replace(b, origin=Origin.YOURS)
                    for b in position.bullets
                ),
            )
            for position in edited.experience
        ),
    )


def settle_revision(current: ResumeContent, proposed: ResumeContent) -> ResumeContent:
    """What a chat proposal really changes.

    A line whose text is unchanged is the line it was — origin and citations
    included — whatever the model says about it. Any other line is the model's
    writing, and must cite evidence like any written line.
    """
    before = {b.text: b for b in current.bullets()}
    return replace(
        proposed,
        experience=tuple(
            replace(
                position,
                bullets=tuple(
                    before[b.text] if b.text in before else replace(b, origin=Origin.WRITTEN)
                    for b in position.bullets
                ),
            )
            for position in proposed.experience
        ),
    )


@dataclass(frozen=True, slots=True)
class Coverage:
    requirement: str
    verdict: Verdict
    dimension_key: str | None
    evidence_ids: tuple[str, ...]


def coverage(
    *,
    requirements: Sequence[str],
    requirement_map: Mapping[str, str | None],
    scores: Mapping[str, int],
    targets: Mapping[str, int],
    evidence: Mapping[str, Sequence[str]],
) -> tuple[Coverage, ...]:
    """Covered, partial or gap for each requirement, with what backs it.

    A requirement mapped to one of the user's dimensions is judged by that
    dimension's score against the Target's bar for it. One mapped to nothing —
    or to a dimension the Target sets no bar for — has no evidence to judge by,
    and is a gap.
    """
    result = []
    for requirement in requirements:
        key = requirement_map.get(requirement)
        if key is None or key not in scores or key not in targets:
            result.append(Coverage(requirement, Verdict.GAP, key, ()))
            continue
        delta = scores[key] - targets[key]
        verdict = (
            Verdict.COVERED
            if delta >= 0
            else Verdict.PARTIAL
            if delta > -PARTIAL_WITHIN
            else Verdict.GAP
        )
        result.append(Coverage(requirement, verdict, key, tuple(evidence.get(key, ()))))
    return tuple(result)
