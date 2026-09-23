# 0006. Report AI job progress through a status the page polls

**Status:** Accepted — 2026-09-23.

## Context

Drafting a gap plan runs on the worker's `ai` queue, on the user's key, and
takes tens of seconds. Until now nothing told the page whether a queued job had
finished or failed: the SPA said "reload in a moment", and a failure — budget
exceeded, key revoked, the model citing evidence the user does not have —
reached only the worker's log.

`docs/technical_boundaries.md` section 6 planned for the SPA to "track job
status over SSE". The api holds no job state to stream from, though: jobs run
in another process, and a stream would need either a pub/sub channel (there is
no Redis, by design) or the api polling the database on the client's behalf.

## Decision

A result that a job produces is created **before** the job runs, with a status,
and the page polls it.

- `POST /gap-plans` resolves the Target (refusing one that cannot be planned
  for straight away), writes the plan row with `status = drafting`, and queues
  `gapplan.draft` with the row's id.
- The job fills the row and sets `ready`, or sets `failed` with the error's
  stable code and message. Expected failures are recorded, not raised: retrying
  would spend the user's key again for the same outcome. An unexpected failure
  is recorded as `internal` and still raised, so it reaches the job log.
- The SPA polls `GET /gap-plans/{id}` every two seconds while it is `drafting`,
  and says what went wrong when it is `failed`.
- The résumé follows the same pattern. Streaming stays where it is the point:
  the résumé revision chat, over SSE from the api.

## Consequences

Easier:
- A failed job says why, in the same `{code, message}` terms as every other
  error, and the page can point at the fix (the model settings for a budget or
  key failure).
- Nothing new to run: no broker, no long-lived connections.
- A plan is visible in history from the moment it is requested.

Harder:
- Polling costs a request every two seconds per open drafting page. Fine at
  this scale; a page left open on a stuck job keeps polling until it leaves.
- Every job-produced table carries `status`, `error_code` and `error_message`,
  and every reader has to handle a row with no content yet.
- A job that dies without reaching its failure handler (the process is killed)
  leaves the row `drafting`. There is no sweeper for that yet.

## Alternatives considered

- **SSE from the api, as planned.** Lost because the api has no job state to
  stream; it would have polled the database itself, adding a connection per
  open page to get the same answer.
- **Read job state from Procrastinate's own tables.** Lost because they know a
  job succeeded or failed, not what the failure means to the user, and reading
  them would tie the api to the job runner's schema.
- **Keep "reload in a moment".** Lost because a failed plan would look exactly
  like a slow one.
