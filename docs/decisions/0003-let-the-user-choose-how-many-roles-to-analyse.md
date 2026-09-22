# 0003. Let the user choose how many roles to analyse

**Status:** Accepted — 2026-09-22. Supersedes [0002](0002-analyse-only-the-ten-closest-roles.md).

## Context

[ADR 0002](0002-analyse-only-the-ten-closest-roles.md) limited a role map to
the ten clusters closest to the user's profile, so the cost of a first run
stopped growing with the market. It deferred letting the user choose the
limit, because there was no settings surface for it.

The updated `docs/intent.md` now asks for exactly that: *"Select the top k
similar role based on the assessment and profile result. User can decide the
number of k by themself."* The user pays for every analysed role on their own
key (domain decision 7), so the choice is theirs too. A user thinking about a
career change wants to see further than ten, and a user on a tight budget
wants fewer.

What 0002 got right still holds. Before any analysis there are no
requirements, so the selection cannot use assessed fit. It has to stay local
and free.

## Decision

The role map analyses the user's top **k** clusters. k is a per-user setting,
bounded to **3–20**, with a default of **10**.

- Selection is unchanged: `rank_by_fit` in `modules/rolemap/domain/selection.py`
  ranks clusters by cosine distance between cluster and profile centroids, with
  the largest clusters as the fallback for an empty profile. Only the cut-off
  moves from a constant to the setting.
- The bound is a domain rule in `rolemap`, checked again by the API schema.
- The setting lives in `rolemap.role_map_setting`, owner zone, one row per user.
- The pre-run cost estimate is capped at k. **Raising k** shows a new estimate
  and runs only after the user confirms. **Lowering k** spends nothing: roles
  outside the new k are retired through the usual reconciliation, and get their
  ids back if they return.
- Changing k emits `RoleCountChanged`, which queues `rolemap.recluster` for that
  user.

## Consequences

Easier:
- The user decides how wide the map is, and pays for exactly that. A career
  changer can widen it; a cautious user can narrow it.
- The estimate the user confirms still has a hard ceiling (20 roles, about 40
  calls), so a role map can never scale with the market.

Harder:
- Cost is no longer the same for everyone, so support and budgeting can't
  assume "at most 20 calls". The ceiling is now 40.
- A settings surface is needed on the role map, with its own confirm step.
- A higher k means more fits in `compute_fits` and more bubbles on the chart.
  Above about 12, labels crowd and the chart needs a denser layout.
- Lowering k retires roles the user may have been looking at. A gap plan or
  résumé aimed at one keeps its frozen requirements snapshot (domain decision
  16), but the role drops off the map.
- `MAX_ROLES_ANALYZED` stops being a constant, and the recluster job has to read
  the setting.

## Alternatives considered

- **Keep a fixed ten (ADR 0002).** Predictable, but the intent now asks for
  the user's choice, and ten is too narrow for a career change.
- **Let k be any number.** Brings back the problem 0002 fixed: a large k puts
  the cost back in proportion to the market, past the default monthly budget.
- **Size k from the budget automatically.** Spends the budget on breadth the
  user didn't ask for, and hides the choice the intent wants to give them.
