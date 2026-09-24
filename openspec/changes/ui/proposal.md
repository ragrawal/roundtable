# Proposal

## Why

Today, operating `roundtable` end to end means hand-editing `roundtable.toml`
to change the agent roster and either tailing herdr panes or querying
`SqliteEventStore` directly to see what a run has done. Both are workable for
the person who built the framework but not for someone who just wants to
configure a roster and watch a review happen. This change adds a web UI for
the two things an operator actually needs day to day: editing the roster
before a run, and watching the structured events a run produces — critiques,
revision requests, consensus/deadlock outcomes, and the artifact versions
they relate to — as they're recorded.

## What Changes

- **Roster editor**: list, create, edit, and delete agents in
  `AgentRoster.agents`, editing exactly the four fields `AgentProfile`
  defines (`name`, `role`, `persona`, `kind`). Client- and server-side
  validation mirrors `AgentRoster`'s own invariants (exactly one developer,
  at least one reviewer, unique names, herdr's name pattern) so the UI can
  never save a roster the runner would reject. Saves rewrite
  `roundtable.toml` in place, preserving `round_limit` and any other
  top-level `RoundtableConfig` field untouched.
- **Concurrent-edit safety via a held OS advisory lock**: an editor session
  acquires a non-blocking `flock` on a `roundtable.lock` file before reading
  `roundtable.toml` and holds it across the whole read-validate-write
  sequence; a second session that can't acquire the lock is told the roster
  is being edited elsewhere and must retry. Lock ownership is never
  reclaimed by age or PID inspection — the OS releases the lock
  automatically if the holding process dies, and that is the only
  crash-recovery mechanism this change relies on.
- **Live event feed**: a real-time, filterable view of the events recorded
  for the specification being viewed (`ArtifactDrafted`, `CritiqueSubmitted`,
  `RevisionRequested`, `ConsensusDeadlocked`, `ConsensusReached`), grouped by
  round, delivered by a backend process that tails `SqliteEventStore` and
  pushes (or is polled for) new events, deduplicated by `event_id`.
- **Run lifecycle status as two always-defined, independent signals**: an
  outcome label derived from the event tail (including a `not started`
  label when no events exist yet) and a connection health derived from the
  live transport, shown together rather than merged, never gating roster
  saves or any other write. A `ConsensusDeadlocked` tail is labeled as an
  ambiguous, possibly-still-active outcome rather than "complete," because
  `ReviewRunner.run` can block on human confirmation after recording it and
  then resume into another round without emitting any event until the next
  critique lands; connection health (e.g. a later disconnect) never
  replaces or hides a reliably terminal `consensus reached` outcome.
- **Artifact version browser**: lists every `ArtifactDrafted` version
  (`version_id`, `emitter`, `timestamp`) and its `content` field, explicitly
  labeled as a reviewer-facing summary, not the complete artifact. Resolving
  `version_id` to full content or a diff is out of scope this iteration —
  neither `ArtifactDrafted` nor the store carries the path or workspace root
  needed to do that deterministically.
- **No changes to existing backend contracts**: every feature above is built
  on `RoundtableEvent`, `EventStoreProtocol`/`SqliteEventStore`, and
  `RoundtableConfig`/`AgentRoster`/`AgentProfile` exactly as they exist
  today. Where a richer feature would need a schema or contract change
  (multi-run history, an authoritative run-lifecycle signal, full-content
  artifact resolution, a store-level replay cursor), this change calls it
  out as a tracked dependency instead of building around the gap.

## Capabilities

### New Capabilities
- `roundtable-web-ui`: an interactive website for authoring a workspace's
  agent roster and observing, in real time, the structured events a
  roundtable review run produces for a specification, plus the artifact
  versions those events relate to.

## Impact

- **New code, no modification to existing modules**: `src/roundtable/events.py`,
  `src/roundtable/store.py`, `src/roundtable/config.py`, and
  `src/roundtable/orchestration.py` are read-only dependencies of this
  change; none of their contracts change.
- **New backend service** (module path TBD in design): read/write HTTP(S)
  endpoints over `RoundtableConfig`/`AgentRoster` for the roster editor, a
  read-only endpoint or push transport over `SqliteEventStore.replay` for
  the event feed and version browser, and the `roundtable.lock`
  advisory-lock protocol for concurrent-edit safety.
- **New frontend application** (framework TBD in design): roster
  editor, live event feed, run status indicator, and artifact version list.
- **New workspace file**: `roundtable.lock`, created beside
  `roundtable.toml` on first roster-editor save; advisory-locked, not
  itself durable state.
- **Tests**: new unit tests for the lock protocol (including a held-lock
  contention case) and lifecycle-status derivation (including the
  deadlock-then-resume ambiguity), plus BDD/end-to-end coverage for the
  roster-edit and live-feed flows. No existing test suite needs to change,
  since no existing contract changes.
- **Not in scope**: multi-user auth, a freeform inter-agent chat transcript
  (none is persisted), true multi-run history/selection, an authoritative
  run-lifecycle signal, full-content/diff artifact resolution, a
  store-level replay cursor, roster fields beyond the four `AgentProfile`
  defines, and a mobile-optimized layout.
