# 0002. Analyse only the ten roles closest to the user's profile

**Status:** Accepted — 2026-09-22

## Context

A role map clusters every posting in the user's scope locally, then spends two
calls on the user's key per cluster: one to name it and extract its
requirements, one to estimate its hiring bar. The number of clusters grows
with the market. A user with about 410 postings in scope could get up to 136
clusters, and the cost shown before the first run came to $88.83. That is past
the default monthly budget, and most of those roles are far from anything the
user has done.

Before the analysis there are no requirements, so the assessed fit
(`assessment`) is not yet available. Whatever picks the clusters has to work
without it and without spending the user's key.

## Decision

A role map analyses at most `MAX_ROLES_ANALYZED` (10) clusters: the ones whose
centroid is closest, by cosine, to the centroid of the user's profile. The
profile side embeds each evidence fact and each position title with the same
local model the postings use. The rule is `rank_by_fit` in
`modules/rolemap/domain/selection.py`. It runs in the worker, as plain
platform-paid computation (domain decision 7).

- With an empty profile, the largest clusters are kept instead.
- Clusters outside the ten are not analysed. A role they held before is
  retired through the usual reconciliation, and gets its id back if it returns.
- The cost estimate is capped at ten roles as well.

## Consequences

Easier:
- A role map costs at most 20 calls, whatever the size of the market. The
  pre-run ceiling becomes a number a user can act on.
- The roles a user sees are the ones worth assessing them against, and
  `compute_fits` does ten fits instead of dozens.

Harder:
- The map no longer shows the whole market. A role far from the profile never
  appears, even when it has many openings. That makes the map worse for a user
  looking at a career change.
- Selection uses embedding similarity as a stand-in for fit. It can rank a
  cluster above one the assessment would score higher.
- A profile change (a new connector, a résumé) can change which ten are kept,
  and retire roles a user was looking at.
- The recluster job now reads the profile and embeds it on every run, which adds
  a dependency from `rolemap` to `profile.public`.

## Alternatives considered

- **Analyse every cluster.** The cost that prompted this record: it scales with
  the market instead of with the user.
- **Rank by the assessed fit.** Fit needs each role's requirements, and those
  come from the analysis being limited. Getting them would spend the key on
  every cluster anyway.
- **Keep the largest clusters.** Free and simple, but it ignores the user. It
  remains only as the fallback for an empty profile.
- **Let the user choose the limit.** Deferred rather than rejected: a fixed ten
  keeps the cost predictable while there is no settings surface for it.
