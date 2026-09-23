"""The rules of a gap plan (domain decision 16, section 2.1).

A plan closes the distance to one Target. The model drafts it — why each gap
matters, the milestones, the tasks, the projects — and these rules decide
whether that draft is acceptable. What the gaps *are*, and how much each is
worth, is not the model's call: that comes from the Target's snapshot.

Task and gap are many-to-many. A task says which gaps it closes; a task done in
one plan counts in every plan where a matching task closes the same gap.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

MIN_MILESTONES = 2
MAX_MILESTONES = 5
MIN_TASKS_PER_MILESTONE = 2
MAX_TASKS_PER_MILESTONE = 5
MAX_PROJECTS = 4

# The prototype's "The four things between you and …": enough to act on, few
# enough that the first one is obviously first.
SHOWN_GAPS = 4

# Two tasks are the same piece of work when they close a common gap and share
# this much of their wording. Regenerating rewords tasks; it should not make
# finished work look unfinished.
TASK_MATCH_THRESHOLD = 0.6

MAX_STEPPING_STONES = 3


class PlanStatus(StrEnum):
    """A plan is drafted by a background job, so it exists before it is ready.

    ``failed`` records why, with the error's stable code, so the page can say
    what went wrong instead of waiting forever.
    """

    DRAFTING = "drafting"
    READY = "ready"
    FAILED = "failed"


class PlanError(ValueError):
    """A drafted plan that breaks the rules; it is rejected, not repaired."""


@dataclass(frozen=True, slots=True)
class GapReading:
    """The model's account of one gap: why it matters, and the work behind it."""

    key: str
    why: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftTask:
    text: str
    due: str
    closes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftMilestone:
    title: str
    window: str
    outcome: str
    tasks: tuple[DraftTask, ...]


@dataclass(frozen=True, slots=True)
class DraftProject:
    """A suggested piece of work with no due date: the prototype's projects."""

    name: str
    note: str
    closes: tuple[str, ...]


def assert_draft_valid(
    *,
    readings: Sequence[GapReading],
    milestones: Sequence[DraftMilestone],
    projects: Sequence[DraftProject],
    shown_keys: Sequence[str],
    dimension_keys: Iterable[str],
) -> None:
    """Every shown gap is explained, and every task closes one of them.

    A dimension gap must cite evidence — it is a claim about the user's work.
    An uncovered requirement has, by definition, nothing to cite.
    """
    shown = set(shown_keys)
    dimensional = set(dimension_keys)

    read_keys = [reading.key for reading in readings]
    if len(read_keys) != len(set(read_keys)):
        raise PlanError("each gap is explained once")
    if unknown := set(read_keys) - shown:
        raise PlanError(f"explained gaps that are not in the plan: {sorted(unknown)}")
    if missing := shown - set(read_keys):
        raise PlanError(f"left gaps unexplained: {sorted(missing)}")
    for reading in readings:
        if not reading.why.strip():
            raise PlanError(f"gap {reading.key} has no explanation")
        if reading.key in dimensional and not reading.evidence_ids:
            raise PlanError(f"gap {reading.key} cites no evidence")

    if not MIN_MILESTONES <= len(milestones) <= MAX_MILESTONES:
        raise PlanError(
            f"a plan has {MIN_MILESTONES}-{MAX_MILESTONES} milestones, not {len(milestones)}"
        )
    for milestone in milestones:
        if not MIN_TASKS_PER_MILESTONE <= len(milestone.tasks) <= MAX_TASKS_PER_MILESTONE:
            raise PlanError(
                f"milestone {milestone.title!r} has {len(milestone.tasks)} tasks; "
                f"each has {MIN_TASKS_PER_MILESTONE}-{MAX_TASKS_PER_MILESTONE}"
            )
        for task in milestone.tasks:
            _assert_closes(task.text, task.closes, shown)

    if len(projects) > MAX_PROJECTS:
        raise PlanError(f"a plan suggests at most {MAX_PROJECTS} projects")
    for project in projects:
        _assert_closes(project.name, project.closes, shown)


def _assert_closes(what: str, closes: Sequence[str], shown: set[str]) -> None:
    if not closes:
        raise PlanError(f"{what!r} closes no gap")
    if unknown := set(closes) - shown:
        raise PlanError(f"{what!r} closes gaps that are not in the plan: {sorted(unknown)}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def tasks_match(
    text: str, closes: Iterable[str], other_text: str, other_closes: Iterable[str]
) -> bool:
    """The same work: a common gap, and mostly the same words."""
    if not set(closes) & set(other_closes):
        return False
    words, other = _words(text), _words(other_text)
    if not words or not other:
        return False
    return len(words & other) / len(words | other) >= TASK_MATCH_THRESHOLD


def carried_done(
    tasks: Sequence[tuple[str, Sequence[str]]],
    done_elsewhere: Sequence[tuple[str, Sequence[str]]],
) -> set[int]:
    """Indices of ``tasks`` already finished as a matching task somewhere else.

    Used both when a plan is regenerated (completion carries into the new
    version) and across plans (a task counts wherever it closes the same gap).
    """
    return {
        index
        for index, (text, closes) in enumerate(tasks)
        if any(tasks_match(text, closes, done, done_closes) for done, done_closes in done_elsewhere)
    }


def progress(done: Sequence[bool]) -> int:
    """Percent of tasks done, 0 for a plan with none."""
    if not done:
        return 0
    return round(100 * sum(done) / len(done))


@dataclass(frozen=True, slots=True)
class RoleOption:
    role_id: str
    name: str
    fit: int
    openings: int


def stepping_stones(
    *, target_role_id: str | None, target_fit: int | None, roles: Sequence[RoleOption]
) -> tuple[RoleOption, ...]:
    """Roles the user already fits better: a credible bridge if the jump is far.

    Only roles with a strictly higher fit, best first, and never the Target's
    own role. With no fit for the Target there is nothing to compare against.
    """
    if target_fit is None:
        return ()
    better = [r for r in roles if r.role_id != target_role_id and r.fit > target_fit]
    better.sort(key=lambda r: (-r.fit, -r.openings, r.name))
    return tuple(better[:MAX_STEPPING_STONES])
