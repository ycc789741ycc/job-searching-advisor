# Decision records

Decisions that are costly to reverse or non-obvious to the next reader. An
accepted record is immutable apart from its status line: a changed mind is a
new record that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-run-our-own-email-password-sign-in.md) | Run our own email-and-password sign-in instead of a hosted provider | Accepted |
| [0002](0002-analyse-only-the-ten-closest-roles.md) | Analyse only the ten roles closest to the user's profile | Superseded by 0003 |
| [0003](0003-let-the-user-choose-how-many-roles-to-analyse.md) | Let the user choose how many roles to analyse (3–20, default 10) | Accepted |
| [0004](0004-build-the-spa-on-the-prototypes-design-system.md) | Build the SPA on the prototype's design system and sidebar shell | Accepted |
| [0005](0005-resolve-targets-in-their-own-module.md) | Resolve Targets in their own module | Accepted |
| [0006](0006-report-ai-job-progress-through-a-status-the-page-polls.md) | Report AI job progress through a status the page polls | Accepted |
| [0007](0007-render-resume-pdfs-with-weasyprint.md) | Render résumé PDFs with WeasyPrint, not a headless browser | Accepted |
| [0008](0008-sign-in-with-google-by-our-own-oidc-exchange.md) | Sign in with Google through our own OpenID Connect exchange, and let a verified address take over an unverified one | Accepted |

Decisions taken before this directory existed are recorded in the tables of
`docs/domain_model_review.md` section 6 and `docs/technical_boundaries.md`
sections 7 and 8.
