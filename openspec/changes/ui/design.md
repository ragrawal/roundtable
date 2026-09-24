# Design

## Context

This is a new, mostly-read UI over existing durable state
(`roundtable.toml` via `RoundtableConfig`, and `SqliteEventStore`). The one
write path — the roster editor — is the only place this design needs a real
concurrency story; everything else is a read/projection problem. Two
decisions below were revised after review found them unsafe or misleading
as first drafted; each keeps the fix and records why the simpler version
didn't work.

## Decision: advisory-lock protocol for roster saves

**What**: a roster save acquires a non-blocking POSIX advisory lock
(`flock(LOCK_EX | LOCK_NB)`) on `roundtable.lock` beside `roundtable.toml`,
holds it across read → validate → write, and releases it when that
sequence ends (success or failure). The write itself is a temp-file-then-
rename for atomicity. If acquisition fails, the caller is told to retry;
nothing about lock age or the previous holder's PID is ever used to reclaim
the lock.

**Why not a mtime/hash check-then-rename ("optimistic" compare-and-swap)?**
The first draft of this change proposed exactly that: read
`roundtable.toml`, remember its mtime, validate the edit, and on save,
compare mtime and rename only if unchanged. That's a classic TOCTOU race —
a second writer can land between the compare and the rename, and both saves
can report success while one silently overwrites the other. A held lock
across the whole sequence removes the gap the race depends on.

**Why not age/PID-based stale-lock reclamation?** The next draft added a
lock file with a recorded PID and timestamp: a lock untouched for 60s was
considered abandoned and could be broken by a new acquirer. Review
(round 4) found this unsafe: a process can legitimately hold the lock
longer than any fixed timeout (a slow disk, a large roster, a paused
debugger), and unlinking or replacing the lock file based on age lets a
second writer proceed while the first writer still believes it holds
exclusive access — the two can now interleave writes exactly as the
mtime-race did. PID and timestamp are also not proof of liveness: PIDs are
reused, and behavior differs across platforms and filesystems.

The fix: let the OS do crash recovery. A `flock` held by a process is
released automatically by the kernel when that process dies, for any
reason. That means a *non-blocking* acquire attempt is always a correct
answer to "is this lock actually free right now?" — no separate staleness
inference is needed, and none is used for reclamation. A staleness
duration is still useful, but only as UX: if a lock has been held past
some threshold, the UI can say "this is taking a while" or adjust a
retry/backoff cadence — it never touches ownership.

**Scope**: this relies on POSIX advisory locks on a local filesystem.
Network filesystems (NFS, etc.) and Windows are out of scope this
iteration; if the workspace ever needs to live on one, this protocol needs
revisiting rather than assumed to carry over.

## Decision: run lifecycle status as two orthogonal signals, with deadlock treated as ambiguous

**What**: status is two independent signals, not one field: an **outcome
label** derived from the event tail (`not started` / `in progress
(estimated)` / `deadlocked (may still be active)` / `consensus reached`),
and a **connection health** derived from the live transport and event
recency (`live` / `stale` / `disconnected`) — see the spec's "Run lifecycle
status" requirement for the exact rules. `ConsensusReached` is the only
tail value this design treats as reliably terminal. `ConsensusDeadlocked`
is shown as "deadlocked (may still be active)," never as "complete." The
two signals are always shown together; connection health never overwrites
or hides the outcome label.

**Why two signals instead of one merged status?** The first draft listed
`consensus reached`, `deadlocked (may still be active)`, `in progress`,
`stale`, and `disconnected` as five cases of a single status field, with
`stale`/`disconnected` explicitly "evaluated independently" of the others.
That's a contradiction in the shape of the model: independence means more
than one of these can be true at once (a `ConsensusReached` tail is
perfectly compatible with the transport later going `disconnected`, and a
`ConsensusDeadlocked` tail sitting untouched for a minute is simultaneously
`deadlocked` and `stale`), but a single field can only hold one value.
Review (round 4) flagged that this leaves an implementation free to pick
either the tail-derived label or the transport-derived label when both
apply, which could — worst case — silently downgrade a reliably terminal
`consensus reached` result to `disconnected` the moment a viewer's tab
loses its connection. Splitting outcome (what the event history says
happened) from connection health (whether the live view of that history is
currently fresh) removes the ambiguity: each is independently well-defined,
both are shown, and the one signal this design calls reliably terminal —
`consensus reached` — can never be hidden by the other.

**Why "not started"?** The first draft's five cases all presupposed at
least one recorded event (`stale` needs a last-event timestamp to compare
against; `in progress` needs a last event that isn't a terminal type).
Review (round 4) pointed out that `replay` returning no events — the
normal state of a specification before its first run, or a brand-new
specification — falls into none of them, leaving an implementation to
guess and risk mislabeling an idle specification as `stale` or
`disconnected`. `not started` is now the outcome label whenever history is
empty, and staleness is explicitly not evaluated against zero events (there
is no timestamp to measure it from) — an empty-history specification's
connection health is `live` or `disconnected` only.

**Why not treat any terminal-shaped event as "complete"?** The first draft
treated both `ConsensusReached` and `ConsensusDeadlocked` as terminal,
reasoning that both are "true terminal events" in the event schema. Review
(round 4) pointed out this conflates *event shape* with *process state*:
`ReviewRunner.run` (`src/roundtable/orchestration.py`) records
`ConsensusDeadlocked`, reports escalation instructions, and then — if given
a `confirm` callback — blocks synchronously on human confirmation. A truthy
result resumes the same run into another critique round, exempt from the
round limit, without re-drafting and without recording any event until that
round's first `CritiqueSubmitted` arrives. During that wait, which can be
arbitrarily long, the event tail is `ConsensusDeadlocked` and the process is
fully alive and about to keep working. `ConsensusReached` has no such
escape hatch: `run()` returns unconditionally on the line immediately after
recording it, so that event genuinely is the end of the run.

Because the confirmation step itself is in-process and not recorded as an
event, there is no event-stream signal available today that would let the
UI distinguish "deadlock, run ended" from "deadlock, run paused awaiting a
human." Rather than guess, the status is labeled as ambiguous. If the run
does resume, the UI doesn't need a dedicated "resumed" event to recover:
the next `CritiqueSubmitted` for the new round arrives normally and the
existing "in progress (estimated)" rule takes over from there.

**Tracked dependency**: an explicit run-start/run-end signal (and a
`run_id`) from the process driving a review would remove this ambiguity
entirely, along with enabling true multi-run selection (see proposal.md's
Impact and the spec's "Run selection" requirement). This change does not
add one; it scopes the UI to what the current event stream actually
supports.

## Decision: full replay + client-side dedup instead of a store cursor

`EventStoreProtocol.replay` returns full history in append order and
exposes no cursor over the store's internal `sequence` column. Rather than
add one now, the backend tailing process does full replay per poll/connect
and diffs against what it has already forwarded, keyed by `event_id`; the
client independently discards anything it has already rendered by the same
key. This is simple and correct at today's expected history sizes (a
handful of rounds per specification) but its cost scales with history
length. A store-level cursor (e.g. `replay(specification_id,
after_sequence=...)`) is a tracked dependency if history size becomes a
real constraint.

## Open questions (tracked dependencies, not blocking this change)

- A `run_id` on `EventEnvelope` and in the store, to support true multi-run
  selection and to remove the deadlock-status ambiguity via an explicit
  run-end signal.
- Artifact path metadata (or a documented phase-to-path mapping plus
  workspace/repository root access) so the version browser could resolve
  full content and diffs.
- A cursor-bounded `replay` query, to bound live-feed cost as history
  grows.
- Whether `CritiqueSubmitted.review_id` and the other events'
  `discussion_id` should be unified into one field name (naming only,
  independent of the round-number-uniqueness issue already called out in
  the spec).
- Frontend framework and backend service language/framework choice — left
  unresolved here; either fits over the read/write surface this design
  describes and neither is forced by it.
