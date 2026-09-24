# Tasks

## 1. Backend: roster read/write

- [ ] 1.1 Add a read endpoint that loads `roundtable.toml` via
  `load_config`/`RoundtableConfig` and returns the roster's four editable
  fields per agent, plus `round_limit`
- [ ] 1.2 Implement the `roundtable.lock` advisory-lock protocol
  (non-blocking `flock`, held across read-validate-write, released on
  completion or failure, no age/PID-based reclamation) as a reusable
  helper, per `design.md`'s "advisory-lock protocol" decision
- [ ] 1.3 Add a write endpoint that: acquires the lock (returning a
  "locked, retry" response if acquisition fails), re-reads
  `roundtable.toml`, applies the roster edit, validates via
  `AgentRoster`'s own validator, writes the whole `RoundtableConfig` back
  (preserving `round_limit` and any other field unchanged) via
  temp-file-then-rename, and releases the lock
- [ ] 1.4 Unit tests: reject-missing-developer, reject-duplicate-names,
  reject-multiple-developers, reject-bad-name-pattern, round_limit
  preserved across an unrelated edit, second acquirer denied while first
  holds the lock, lock released and reacquirable immediately after the
  holding process dies (no age dependency) — verify via
  `uv run pytest tests/unit/test_roster_api.py -v` (or equivalent)

## 2. Backend: event feed and version browser

- [ ] 2.1 Add a read endpoint/transport that tails
  `SqliteEventStore.replay(specification_id)` and streams new events
  (push transport, or full-replay-plus-diff-by-`event_id` polling per
  `design.md`) to connected clients
- [ ] 2.2 Add round-number grouping (`review_id`/`discussion_id`) and
  emitter/event-type/round/keyword filtering to the feed endpoint
- [ ] 2.3 Add a version-list endpoint deriving entries from
  `ArtifactDrafted` events only, exposing `version_id`, `emitter`,
  `timestamp`, `content` — no full-content or diff resolution
- [ ] 2.4 Implement lifecycle-status derivation as the two independent
  signals the spec's "Run lifecycle status" requirement defines — outcome
  label (`not started` / `in progress (estimated)` / `deadlocked (may
  still be active)` / `consensus reached`) and connection health (`live` /
  `stale` / `disconnected`) — returning both, never merged into one field,
  per `design.md`
- [ ] 2.5 Unit tests: dedup by `event_id` across repeated polls; outcome
  label = `not started` on an empty `replay` result; connection health on
  an empty `replay` result is `live` or `disconnected` only, never `stale`;
  outcome label = `consensus reached` only on a `ConsensusReached` tail and
  remains `consensus reached` after connection health flips to
  `disconnected`; outcome label = `deadlocked (may still be active)` (not
  `complete`) on a `ConsensusDeadlocked` tail, including together with a
  `stale` connection health; outcome label transitions to `in progress`
  once a post-deadlock `CritiqueSubmitted` arrives; `stale` vs.
  `disconnected` computed independently — verify via
  `uv run pytest tests/unit/test_event_feed.py -v` (or equivalent)

## 3. Frontend: roster editor

- [ ] 3.1 List/create/edit/delete agents (`name`, `role`, `persona`,
  `kind` only), with client-side validation mirroring `AgentRoster`'s
  invariants surfaced inline before submit
- [ ] 3.2 Handle the "locked, retry" response from a contended save
  without letting the operator believe the save succeeded
- [ ] 3.3 Surface server-side validation failures using the same message
  text the backend forwards from `AgentRoster`'s validator

## 4. Frontend: live event feed, status, and version browser

- [ ] 4.1 Render the event feed grouped by round number, filterable by
  emitter/event type/round/keyword, with each item's full type-specific
  payload
- [ ] 4.2 Render the lifecycle status with the muted/estimate treatment
  the spec requires, including the distinct "deadlocked (may still be
  active)" label — never a hard "complete" indicator for a deadlock tail
- [ ] 4.3 Render the artifact version list with each entry's `content`
  visibly labeled as a summary
- [ ] 4.4 Handle connection loss: retain rendered events, mark
  disconnected, retry with backoff, without clearing prior state

## 5. End-to-end verification

- [ ] 5.1 BDD/e2e coverage: full roster edit-and-save round trip against a
  real `roundtable.toml`; a second concurrent session denied and then
  succeeding after retry; a live feed reflecting events as they're
  appended to a real `SqliteEventStore`; status transitioning from
  deadlocked-ambiguous to in-progress when a resumed round's critique
  arrives
- [ ] 5.2 Run the full check suite (lint, type-check, tests with coverage
  floor) and `openspec validate ui --strict`, and confirm both pass
