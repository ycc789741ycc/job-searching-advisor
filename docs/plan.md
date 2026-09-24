# Phase 1
## Login
* User create account in the system — **done as own email + password**, no
  external provider. Address verification and password reset are not built
  yet: both need email delivery, which is still undecided.

## Sources Connector
* Jira
* Github
* User upload resume

## LLM Configuration
* Able to setup and connect under user account

## Job Platform for Role Map Analysis
**Changed during implementation.** Glassdoor, Indeed and LinkedIn cannot be
crawled — their terms forbid it, and LinkedIn has litigated it
(`domain_model_review.md` decision 6). Replaced by sources that permit it:

* Public ATS job boards: Greenhouse, Lever, Ashby — driven by the companies a
  user watches
* Career pages carrying schema.org `JobPosting` JSON-LD
* JDs the user pastes, which stay private to them
* A company with none of the above gets `manual` coverage: it says plainly that
  nothing updates automatically, and offers "paste a JD" instead

LinkedIn remains a *profile* connector (the user's own data, via OAuth) in a
later phase — never a market data source.

## Role Map
## Assessment

# Phase 2
## Gap Plan
* **Done.** Plan a route to a Target: one of the top matched openings, a role
  you watch, or a JD you paste ("My own JD"). The Target's requirements are
  frozen into the plan, so it survives the posting expiring or the role
  re-clustering (domain decision 16, ADR 0005).
* The gaps are ranked by the fit points each is worth — the fit's own
  arithmetic, not the model's opinion. Requirements with no evidence at all
  come first on a tie. The model explains each gap, citing the user's
  evidence, and drafts milestones, tasks and projects; a draft that invents
  evidence or skips a gap is rejected.
* Drafting runs on the user's key after a cost estimate, as a job the page
  polls; a failure says why (ADR 0006).
* Regenerating adds a version and carries finished tasks over; a task done in
  one plan counts in every plan where a matching task closes the same gap.
  Plan history lists each Target's latest version.
* Stepping stones: up to three roles the user already fits better.
* Not yet: suggesting a successor Target when its role splits or merges —
  rolemap does not emit that event yet.

## Resume Advisor
* **Done.** Write for a Target — a top matched opening, a watched role, or a
  pasted JD ("My own JD", scored on the user's key first). Filters are by where
  an opening was found (ATS board, careers page, public job API, watchlist),
  never LinkedIn, Indeed or Glassdoor.
* The first version is written from the user's evidence, revising their
  uploaded résumé when there is one. Every line the model writes cites the
  evidence behind it — the grey note under each line — and a draft that cites
  nothing, or evidence the user does not own, is rejected.
* "Their requirements → your evidence": covered, partial or gap for each
  requirement, decided by the user's scores against the Target's bar, not by
  the model.
* Edit any line in place; "Save this version" keeps a new version, and a line
  the user rewrote is marked as theirs. Saved résumés list every Target
  written for, and reopen at their latest version.
* "Revise with {model}": a chat that streams its answer and proposes a
  revision, applied as a new version only when the user says so.
* Three templates (Warm, Plain, Brief) and export to a white PDF with a
  short-lived download link (ADR 0007).
* Not yet: the interview-report prompt two weeks after tailoring.

# Phase 3
## Support OAuth login
* **Done.** Google — our own OpenID Connect code exchange (PKCE, state, nonce)
  in `identity`, which ends by issuing *our* session: the same access token and
  rotating refresh cookie as a password sign-in (ADR 0008).
* A Google address is verified, so an existing password account at the same
  address is linked, and its password and sessions are removed — our own
  addresses never were verified, so whoever registered one first must not keep
  a way in.
* Optional per deployment: blank `GOOGLE_OAUTH_CLIENT_ID` and the sign-in
  screen offers email and password only.
* Not yet: unlinking Google, or linking it from Settings.
