# 0004. Build the SPA on the prototype's design system and sidebar shell

**Status:** Accepted — 2026-09-23.

## Context

`prototype/Career Advisor.dc.html` is the agreed picture of the product. It is
built on the **Organic** design system (`prototype/_ds/organic-*`): cream
ground, terracotta and olive accents, Caprasimo headings over Figtree, pill
controls. It lays the app out as a 246px left sidebar that numbers the journey
01–06 (Sources, Questions, Strengths, Role map, Gap plan, Résumé), keeps the
model settings apart as "system configuration", and gives every screen a
kicker, a title, a model chip and a target chip.

Phase 1 shipped a different look: a top tab bar, system fonts, and tokens taken
from the dataviz reference palette (blue and orange series, light and dark
modes). Phase 2 adds the Gap plan and Résumé screens, whose layouts only make
sense in the prototype's frame. Building them in the prototype's style next to
five screens in another style would leave the app looking like two products.

## Decision

The whole SPA adopts the prototype's design system and shell.

- `web/src/styles/organic.css` is the prototype's stylesheet, vendored verbatim
  except for its Google Fonts `@import`. The two font families are self-hosted
  as woff2 files under `web/src/styles/fonts/` (both SIL OFL 1.1, licences
  alongside), so the browser makes no third-party request.
- `web/src/styles/tokens.css` keeps the role names every component and chart
  already uses (`--surface-1`, `--series-1`, `--status-critical`, …) and maps
  them onto Organic ramp steps. Nothing below it names a raw colour.
- `web/src/styles/app.css` names the patterns the prototype repeats inline —
  panel, inset, callout, eyebrow, pill toggle, round checkbox, "you vs bar",
  fit and verdict badges, toast — with the prototype's measurements. Screens
  compose them through `components/ui.tsx`.
- The shell is the prototype's: sidebar, page header, and the screen in the URL
  hash (`#/plan`) so a reload keeps it.
- Where the prototype's copy contradicts a decision already taken, the decision
  wins: nothing is "saved in this browser" (domain decision 3), subscriptions
  are checked weekly (decision 14), and no LinkedIn, Glassdoor or Indeed data is
  shown (decision 6).

## Consequences

Easier:
- New screens are assembled from named pieces that already look like the
  prototype, rather than restyled one inline style at a time.
- The prototype stays a usable reference: a screen can be compared with it side
  by side.

Harder:
- **Light only.** Organic has no dark variant and neither does the prototype, so
  the dark mode Phase 1 had is gone.
- **The chart palette is no longer the validated dataviz default.** Terracotta
  and olive were chosen for brand, not checked for colour-vision deficiency.
  The series are one ramp step darker than the prototype so marks clear 3:1
  against the panel surface, and the second series is dashed so the pair never
  relies on colour alone — but that is a mitigation, not a validation.
- **The vendored stylesheet drifts silently.** When the prototype's design
  system changes, `organic.css` has to be re-copied by hand; nothing checks it.
- Organic has no error colour, so `--status-critical` is the one value defined
  outside the system.

## Alternatives considered

- **Style only the new Phase 2 screens like the prototype.** Lost because the
  app would switch look between the Role map and the Gap plan, one click apart.
- **Keep the Phase 1 tokens and copy only the prototype's layout.** Lost because
  the layout without the type and colour doesn't read as the prototype, and the
  prototype is what was agreed.
- **Load the fonts from Google Fonts, as the design system does.** Lost because
  every page view would tell a third party that this user opened the app, for
  two font files that are free to host.
- **Depend on `@fontsource/*` npm packages for the fonts.** Lost for now: the
  repo has no containerised target that regenerates `web/package-lock.json`, and
  the files are small and never change. Adding that target is the better
  long-term fix if more web dependencies arrive.
