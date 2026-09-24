# 0008. Sign in with Google through our own OpenID Connect exchange, and let a verified address take over an unverified one

**Status:** Accepted — 2026-09-24.

## Context

Phase 3 adds Google login (`docs/plan.md`). ADR 0001 made `identity` the owner
of sign-in, and it said Google would be "an OAuth code exchange in `identity`
that ends by issuing our own session", not a switch on a hosted provider. The
session is already fixed: a 15-minute access token held in memory, and a
rotating refresh token in an `HttpOnly`, `SameSite=Strict` cookie scoped to
`/api/v1/auth`.

Several facts shaped the choices:

- **When Google sends the browser back, there is no access token yet.** The
  connector flow (GitHub, Jira) lands in the SPA, because finishing it needs
  the signed-in user's token. A sign-in flow has no such token.
- **Our addresses are unverified.** There is still no email delivery, so anyone
  can register a password account at an address they do not own. Google tells
  us when it has verified an address.
- **An account may end up with a password, Google, or both.** ADR 0001 kept
  `password_credential` off `account` so that another sign-in method would sit
  beside it.

## Decision

- **The callback lands on the API, not the SPA.**
  - `GET /api/v1/auth/google/start` redirects to Google.
  - `GET /api/v1/auth/google/callback` finishes the exchange, sets our usual
    refresh cookie, and redirects to the SPA.
  - The SPA picks the session up through the refresh it already does on load,
    so the client holds no new state.
  - A failure returns to the SPA with only a stable code
    (`?sign_in_error=declined`, `state_mismatch`, `unverified_email`, …).
    Provider detail never reaches the page.
- **The flow is the authorization code flow with PKCE (S256), a `state` and a
  `nonce`.**
  - The three values travel in one HMAC-signed cookie, `jsa_google_attempt`.
    It is valid for 10 minutes, `HttpOnly`, scoped to `/api/v1/auth/google`,
    and deleted once the callback has run.
  - It is `SameSite=Lax`: Google's redirect back is a cross-site navigation,
    and the browser would not send a Strict cookie on it.
  - No table holds attempts that are never finished.
- **The ID token is verified against Google's published keys.** The checks
  are the RS256 signature, issuer (`https://accounts.google.com` or
  `accounts.google.com`), audience (our client id), expiry, nonce, and
  `email_verified`. We check these even though the token arrived straight
  from the token endpoint over TLS. The keys come through the existing
  `JwksResolver`.
- **Outside identities live in a new table, `identity.federated_identity`.**
  - Each row holds a provider and a subject, unique together, with at most
    one identity per provider for an account.
  - The key is Google's `sub`, not the address, because a Google account can
    change its address.
  - The table has the same conditional row-level-security policy as the other
    authentication tables. `account.auth_subject`, a leftover from the hosted
    provider, stays null.
- **Accounts are resolved in this order:**
  1. An identity that is already linked signs in to its account.
  2. Otherwise, an account with the same normalised address is **linked**. If
     that account has a password, **the password is deleted and every session
     it holds is revoked**.
  3. Otherwise, a new account and its AI budget are created.

  If the address belongs to an account already linked to a *different* Google
  identity, the sign-in is refused (`account_conflict`).
- **Google is optional.** It is off while `GOOGLE_OAUTH_CLIENT_ID` is blank,
  and `GET /auth/methods` tells the sign-in screen whether to offer it. Once
  the client id is set, the api refuses to start without the secret, the
  three endpoint URLs and `AUTH_PUBLIC_API_BASE_URL`.

## Consequences

Easier:

- Someone who signs in with Google has a verified address, and they need no
  password or password reset.
- The pre-registration hijack is closed for anyone who uses Google. Whoever
  registered their address first loses the account the moment its owner
  signs in.
- Only sign-in changed. Every downstream request sees the same access token,
  the same refresh rotation and the same row-level security.

Harder:

- **A linked password user loses their password without being asked.** It
  is the right call against a squatter, but a real owner who used both finds
  their password no longer works. The sign-in screen says so when Google is
  offered. They have no way to set a password again until password reset
  exists.
- **A Google-only account depends on Google.** It has no other way in, so
  when Google is down or the client is misconfigured, those users cannot sign
  in.
- **There is no unlinking and no way to add Google from Settings.** Linking
  happens only through the address match at sign-in.
- **There is now a runtime dependency on Google's key set.** The first sign-in
  after a key rotation fetches it, blocking a worker thread rather than the
  event loop.
- **A `SameSite=Lax` cookie now exists in the auth path.** It is narrowly
  scoped, lives for 10 minutes and carries no session, but it is no longer
  true that every auth cookie is Strict.
- **A second Google identity at an address already linked is refused.** That
  happens, for example, when a Workspace address is reassigned to another
  person. Support would have to unlink it by hand.

## Alternatives considered

- **Land the callback in the SPA, as connectors do, and POST the code to
  the API.** This keeps one callback pattern, but the SPA would have to carry
  `state` and the PKCE verifier in storage that scripts can read. It also
  adds a hop for no benefit, since there is no access token to protect. It
  lost on both counts.
- **Store attempts in a table.** Rows could be revoked from the server side,
  but they would need cleanup and a bootstrap row-level-security exception,
  just to track an attempt that lasts 10 minutes. A signed cookie gives the
  same guarantees. The table lost on weight.
- **Refuse the sign-in when the address has a password account, and link
  from Settings after a password sign-in.** This is the most conservative
  option, but a squatter who registered the address first blocks the real
  owner indefinitely. It lost because it protects the squatter.
- **Link and keep the password.** This is the smoothest for a real owner who
  used both, and it is the classic pre-account-takeover hole. It lost
  outright.
- **Reuse `account.auth_subject`.** No migration would be needed, but one
  column cannot hold a provider, cannot hold a second provider later, and
  records nothing about the link. It lost for the same reason
  `password_credential` is its own table.
- **Skip the ID token's signature check because it came straight from the
  token endpoint over TLS.** OpenID Connect allows this, but it leaves one
  less check. `JwksResolver` already existed, so checking the signature cost
  almost nothing.
