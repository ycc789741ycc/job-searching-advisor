# 0005. Resolve Targets in their own module

**Status:** Accepted — 2026-09-23.

## Context

Domain decision 16 makes a **Target** what both a gap plan and a résumé aim at:
a matched posting, a subscribed role, or a JD the user pasted, with a frozen
snapshot of what it requires. `docs/technical_boundaries.md` drew the Target
inside the Gap plan context, because the plan is what keys on it, and said the
Resume context "uses the same value".

Two of our own import rules make that impossible to build as drawn:

- Rule 7: domain feature packages never import each other. A concept two
  features need gets its own feature package.
- Rule 8: `modules.<m>` imports only `domain.<m>`.

If the Target lived in `domain.gapplan`, `modules.resume` could not use it
without going through `modules.gapplan.public` — making résumé writing depend
on gap planning for a concept that belongs to neither. Resolving a Target also
needs four other modules (assessment for fit, rolemap for requirements, market
for subscriptions and pasted JDs, profile indirectly), which is a lot of
knowledge to put in either consumer.

## Decision

The Target gets its own feature package and its own module:

- `domain/target/`: `TargetKind`, `TargetRef` and `TargetSnapshot` — the frozen
  requirements, the user's gaps against them with what each is worth, the
  requirements with no evidence at all, and which dimension each requirement
  mapped to. Pure, like every domain package.
- `modules/target/`: `TargetService`, with **no tables**. It lists what a user
  can aim at (`GET /targets`) and resolves one into a snapshot through the other
  modules' `public.py`. The plan or résumé that keys on a Target stores the
  snapshot itself.
- A pasted JD has no Role, so resolving one reads its requirements and scores
  it on the user's key (`AssessmentService.fit_for_private_posting`), once per
  analysis. Every other kind resolves without AI.
- How much each gap is worth comes from the fit arithmetic itself
  (`domain.assessment.closing_lifts`), not from the model, so plans rank gaps
  the same way the fit score counts them.

## Consequences

Easier:
- `gapplan` and, next, `resume` both depend on one small public surface and
  store the same snapshot shape, so a plan and a résumé for the same Target
  agree on what it requires.
- The import contracts stay as they are: each module still uses only its own
  domain package. Two contracts were added, one per new module.

Harder:
- One more module to wire and to keep in the contracts, and it has no storage of
  its own — someone looking for "the target table" will not find one.
- `target` sits above `assessment`, `market` and `rolemap`, so a change to how
  any of them reports fit or requirements can break Target resolution. The
  integration tests for gap plans exercise that path.
- `assessment.role_fit` now records the requirements and the
  requirement-to-dimension mapping it was projected from. Fits taken before this
  change have neither; their snapshots fall back to the Role's current
  requirements and an empty mapping until fit is re-scored.

## Alternatives considered

- **Keep the Target in `gapplan`, as the boundaries document drew it.** Lost on
  rule 8: `resume` would have to import planning to aim a résumé.
- **Duplicate the resolution in `gapplan` and `resume`.** Lost because the two
  would drift, and a plan and a résumé for the same Target would disagree about
  what it requires.
- **Put resolution in `assessment`, which already owns fit.** Lost because a
  Target also needs subscriptions and pasted JDs from `market` and requirements
  from `rolemap`; `assessment` would become the place everything meets.
