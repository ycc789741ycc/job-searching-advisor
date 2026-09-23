"""Target snapshots, gap-plan rules, carry-over and stepping stones."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from domain.assessment import SkillGap, UncoveredRequirement, closing_lifts
from domain.gapplan import (
    DraftMilestone,
    DraftProject,
    DraftTask,
    GapReading,
    PlanError,
    RoleOption,
    assert_draft_valid,
    carried_done,
    progress,
    stepping_stones,
    tasks_match,
)
from domain.target import (
    DimensionGap,
    Requirement,
    RequirementBasis,
    TargetError,
    TargetKind,
    TargetRef,
    TargetSnapshot,
    UncoveredGap,
    gap_key_for_uncovered,
)


def snapshot(**overrides: object) -> TargetSnapshot:
    values: dict[str, object] = {
        "ref": TargetRef(TargetKind.MATCHED_POSTING, "p1"),
        "title": "Senior Backend Engineer",
        "company": "Northwind Pay",
        "role_id": "r1",
        "role_name": "Senior Backend Engineer",
        "requirements": (Requirement("Own a payments service", 1.0, "advanced"),),
        "basis": RequirementBasis.ROLE,
        "fit_score": 71,
        "dimensions": (
            DimensionGap("leadership", "Leadership", 60, 80, lift=10),
            DimensionGap("craft", "Craft", 90, 70, lift=0),
            DimensionGap("reliability", "Reliability", 50, 70, lift=10),
        ),
        "uncovered": (UncoveredGap("Kubernetes in production", 0.5, lift=10),),
        "requirement_map": {"Own a payments service": "craft"},
        "taken_at": datetime(2026, 9, 23, tzinfo=UTC),
    }
    values.update(overrides)
    return TargetSnapshot(**values)  # type: ignore[arg-type]


# -- the target -----------------------------------------------------------


def test_a_target_with_no_requirements_cannot_be_planned_for() -> None:
    with pytest.raises(TargetError, match="paste its job description"):
        snapshot(requirements=())


def test_open_gaps_leave_out_what_is_cleared_and_put_no_evidence_first_on_a_tie() -> None:
    keys = [gap.key for gap in snapshot().open_gaps]
    assert keys == [
        "req:kubernetes-in-production",
        "dim:leadership",
        "dim:reliability",
    ]


def test_open_gaps_rank_by_what_each_is_worth() -> None:
    ranked = snapshot(
        dimensions=(DimensionGap("leadership", "Leadership", 40, 90, lift=30),),
    ).open_gaps
    assert [gap.key for gap in ranked] == ["dim:leadership", "req:kubernetes-in-production"]


def test_a_snapshot_survives_being_stored() -> None:
    original = snapshot()
    assert TargetSnapshot.from_dict(original.to_dict()) == original


def test_an_uncovered_gap_keeps_its_key_when_reworded_only_in_case_and_spacing() -> None:
    assert gap_key_for_uncovered("Kubernetes in production") == gap_key_for_uncovered(
        "  kubernetes IN production "
    )


def test_a_target_reads_as_role_and_company() -> None:
    assert snapshot().label == "Senior Backend Engineer · Northwind Pay"
    pasted = snapshot(role_name=None, title="Staff Engineer")
    assert pasted.label == "Staff Engineer · Northwind Pay"


# -- what each gap is worth -----------------------------------------------


def test_closing_a_gap_is_worth_its_share_of_the_fit() -> None:
    lifts = closing_lifts(
        gaps=[SkillGap("a", 70, 90), SkillGap("b", 80, 60)],
        uncovered=[UncoveredRequirement("no evidence", 0.5)],
    )
    # Denominator 90 + 60 + 50 = 200.
    assert lifts.by_dimension == {"a": 10}
    assert lifts.by_uncovered == (25,)


def test_nothing_to_close_is_worth_nothing() -> None:
    lifts = closing_lifts(gaps=[], uncovered=[])
    assert lifts.by_dimension == {}
    assert lifts.by_uncovered == ()


# -- the drafted plan -----------------------------------------------------

SHOWN = ["req:k8s", "dim:leadership"]


def milestone(*closes: str, tasks: int = 2) -> DraftMilestone:
    return DraftMilestone(
        title="Own one outcome",
        window="Weeks 1-6",
        outcome="Proof for the panel.",
        tasks=tuple(DraftTask(f"Task {i}", f"Wk {i}", closes) for i in range(tasks)),
    )


def readings(**overrides: GapReading) -> list[GapReading]:
    base = {
        "req:k8s": GapReading("req:k8s", "No evidence at all.", ()),
        "dim:leadership": GapReading("dim:leadership", "Short of the bar.", ("e1",)),
    }
    base.update(overrides)
    return list(base.values())


def check(**overrides: object) -> None:
    arguments: dict[str, object] = {
        "readings": readings(),
        "milestones": [milestone("dim:leadership"), milestone("req:k8s")],
        "projects": [DraftProject("A runner", "Builds evidence.", ("req:k8s",))],
        "shown_keys": SHOWN,
        "dimension_keys": ["dim:leadership"],
    }
    arguments.update(overrides)
    assert_draft_valid(**arguments)  # type: ignore[arg-type]


def test_a_well_formed_plan_passes() -> None:
    check()


def test_every_shown_gap_must_be_explained() -> None:
    with pytest.raises(PlanError, match="unexplained"):
        check(readings=readings()[1:])


def test_a_gap_that_is_not_in_the_plan_cannot_be_explained() -> None:
    extra = GapReading("dim:invented", "Made up.", ("e1",))
    with pytest.raises(PlanError, match="not in the plan"):
        check(readings=[*readings(), extra])


def test_a_skill_gap_must_cite_evidence_but_a_missing_requirement_cannot() -> None:
    with pytest.raises(PlanError, match="cites no evidence"):
        check(readings=readings(**{"dim:leadership": GapReading("dim:leadership", "Why.", ())}))


@pytest.mark.parametrize("count", [1, 6])
def test_a_plan_has_two_to_five_milestones(count: int) -> None:
    with pytest.raises(PlanError, match="milestones"):
        check(milestones=[milestone("dim:leadership")] * count)


@pytest.mark.parametrize("tasks", [1, 6])
def test_a_milestone_has_two_to_five_tasks(tasks: int) -> None:
    with pytest.raises(PlanError, match="tasks"):
        check(milestones=[milestone("dim:leadership", tasks=tasks), milestone("req:k8s")])


def test_every_task_closes_a_gap_in_the_plan() -> None:
    with pytest.raises(PlanError, match="closes no gap"):
        check(milestones=[milestone(), milestone("req:k8s")])
    with pytest.raises(PlanError, match="not in the plan"):
        check(milestones=[milestone("dim:other"), milestone("req:k8s")])


# -- carrying finished work -----------------------------------------------


def test_a_reworded_task_closing_the_same_gap_is_the_same_work() -> None:
    assert tasks_match(
        "Lead the checkout migration epic",
        ["dim:leadership"],
        "Lead the checkout migration epic end to end",
        ["dim:leadership"],
    )


def test_similar_words_for_a_different_gap_are_different_work() -> None:
    assert not tasks_match(
        "Lead the checkout migration epic",
        ["dim:leadership"],
        "Lead the checkout migration epic",
        ["dim:reliability"],
    )


def test_unrelated_work_for_the_same_gap_does_not_match() -> None:
    assert not tasks_match(
        "Write a design doc", ["dim:leadership"], "Mentor two engineers", ["dim:leadership"]
    )


def test_carried_done_names_the_new_tasks_already_finished() -> None:
    new = [("Lead the checkout migration epic", ["g"]), ("Write the RFC", ["g"])]
    done = [("Lead checkout migration epic", ["g"])]
    assert carried_done(new, done) == {0}


def test_progress_is_the_share_of_tasks_done() -> None:
    assert progress([True, False, False, False]) == 25
    assert progress([]) == 0


# -- stepping stones ------------------------------------------------------


def test_stepping_stones_are_the_roles_that_already_fit_better_best_first() -> None:
    roles = [
        RoleOption("target", "Staff", 60, 3),
        RoleOption("a", "Senior Backend", 82, 4),
        RoleOption("b", "Platform", 71, 9),
        RoleOption("c", "Lower", 55, 20),
        RoleOption("d", "Also better", 75, 1),
        RoleOption("e", "Best", 90, 2),
    ]
    stones = stepping_stones(target_role_id="target", target_fit=60, roles=roles)
    assert [s.role_id for s in stones] == ["e", "a", "d"]


def test_with_no_fit_for_the_target_there_is_nothing_to_step_towards() -> None:
    assert (
        stepping_stones(target_role_id=None, target_fit=None, roles=[RoleOption("a", "A", 99, 1)])
        == ()
    )
