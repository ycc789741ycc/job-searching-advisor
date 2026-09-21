# 0001. Run our own email-and-password sign-in instead of a hosted provider

**Status:** Accepted — 2026-09-21

## Context

Phase 1 needs "user creates account in the system" (`docs/plan.md`). The
original plan chose a managed provider, Clerk, and recorded that in
`docs/technical_boundaries.md` section 8. Clerk is hosted-only: using it means
registering an account at clerk.com and pasting four values into `.env` before
the SPA can render anything past a configuration error.

Since then the project moved to running everything in containers, with a
contributor installing only Docker and `make`. An external account as a
prerequisite for opening the app sits badly with that, and it blocked local
use outright.

Two facts shaped the options:

- The backend was never provider-specific. `kernel/auth` verifies a JWT
  through a `SigningKeyResolver`; only the SPA depended on Clerk's React
  components.
- There is no email delivery yet (section 8, question 3), so anything that
  needs to send mail cannot ship in Phase 1.

## Decision

The `identity` module owns sign-in end to end.

- **Passwords** are hashed with Argon2id at OWASP's first-listed parameters
  (19 MiB, 2 iterations, 1 lane), and rehashed on sign-in whenever those
  parameters rise. Policy is length-first: at least 12 characters, a short
  list of first-guessed passwords refused, no composition rules.
- **Guessing** is slowed by a lockout after 5 failures that lifts after 15
  minutes — time-based, so it cannot be used to lock someone out for good.
  "Unknown address" and "wrong password" return the same message and spend
  the same hashing work, so sign-in does not reveal who has an account.
- **Access tokens** are HS256 JWTs signed with `AUTH_JWT_SECRET`, valid for
  15 minutes, returned in the response body and held only in the SPA's
  memory. HS256 because this application is the only issuer and the only
  verifier.
- **Refresh tokens** are 32 random bytes, stored as SHA-256 digests, sent as
  an `HttpOnly`, `SameSite=Strict` cookie scoped to `/api/v1/auth`, and valid
  for 30 days. They **rotate**: each use retires the token and issues a
  replacement in the same family. Presenting a retired token revokes the
  whole family, because replay and theft look identical.
- **Authentication tables** (`identity.password_credential`,
  `identity.refresh_token`) carry the same conditional row-level-security
  policy as `identity.account`: open when `app.user_id` is unset, which only
  the authentication path does, and owner-scoped otherwise.

## Consequences

Easier:

- The app runs with no external account and no network dependency for
  sign-in; `make start-app` is enough.
- One fewer third party holding user identities, and one fewer vendor SDK in
  the bundle.
- Requests authenticate without a database round trip: the token subject is
  the account id.
- A later move to a hosted or self-hosted OpenID provider stays a wiring
  change: `TokenVerifier` already accepts a `JwksResolver`.

Harder:

- **We own the security of sign-in.** Hashing parameters, lockout tuning,
  secret rotation and every future auth bug are ours, where a provider would
  have carried them.
- **No password reset.** Someone who forgets their password has no way back
  in until email delivery exists. The sign-in screen says so.
- **No address verification.** Anyone can register an address they do not
  own. Nothing is sent to it yet, so the exposure is small, but verification
  must land before any notification feature does.
- **Phase 2 Google login is real work** rather than a provider toggle: an
  OAuth code exchange in `identity` that ends by issuing our own session.
- **Rotating `AUTH_JWT_SECRET` signs everyone out.** That is the intended
  emergency control, but it is the only one.
- **Lockout is per account, not per source.** A distributed guess against
  many accounts is not slowed. Rate limiting by client address belongs at
  the edge once there is one.

## Alternatives considered

- **Keep Clerk.** Zero code change and the most mature option, but it needs
  an external account before the app is usable, and it lost on exactly that.
- **Self-hosted Keycloak in compose.** No external account and the most
  standard OpenID provider, but a JVM service of roughly 700 MB to run for
  one sign-in form, plus its own realm configuration to keep in sync. It
  lost on weight.
- **Self-hosted Zitadel in compose.** Lighter than Keycloak and able to share
  our Postgres, but still a second identity system to operate and upgrade,
  and less widely deployed. It lost for the same reason at smaller scale.
- **RS256 with a published JWKS for our own tokens.** Would let other
  services verify tokens without the secret. There are no other services,
  so it added a key pair to manage for no present benefit.
- **Access token in `localStorage`.** Simpler to wire, but readable by any
  script on the page. Keeping it in memory and the refresh token in an
  `HttpOnly` cookie means a cross-site scripting bug cannot steal a session.
