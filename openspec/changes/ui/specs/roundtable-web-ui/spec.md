# Spec Delta

## Purpose

Defines an interactive website for two operator workflows around a
`roundtable` workspace: authoring the agent roster used by a review run
(`RoundtableConfig`/`AgentRoster`), and observing, in real time, the
structured events (`RoundtableEvent`) a run records for a specification,
including the artifact versions those events relate to. It is a read-mostly
view over the existing event store and config file plus one narrow write
path (the roster editor); it does not change what the runner records or how
it decides outcomes.

## ADDED Requirements

### Requirement: Roster listing and field scope

The UI SHALL list every agent in the workspace's `AgentRoster.agents` and
SHALL allow creating, editing, and deleting agents using exactly the four
fields `AgentProfile` defines: `name`, `role`, `persona`, `kind`. The UI
SHALL NOT expose or persist any field `AgentProfile` does not define (e.g. a
model id, a tool-permission list, an enabled flag, a review rubric, or a
per-run active subset).

#### Scenario: Listing the current roster
- **WHEN** an operator opens the roster editor for a workspace
- **THEN** every agent in `roundtable.toml`'s `roster.agents` is shown with
  its `name`, `role`, `persona`, and `kind`

#### Scenario: Editing is limited to defined fields
- **WHEN** an operator edits an agent
- **THEN** only `name`, `role`, `persona`, and `kind` are editable
- **AND** no other field is offered or written back to `roundtable.toml`

### Requirement: Roster save validation

The UI SHALL validate a roster edit against `AgentRoster`'s own invariants —
exactly one agent with `role == "developer"`, at least one other agent, 
unique `name` values across the roster, and each `name` matching herdr's
naming pattern (`^[a-z][a-z0-9_-]{0,31}$`) — both client-side before
submission and server-side before writing, and SHALL surface a failure using
the same message `AgentRoster`'s validator raises. The UI SHALL NOT persist
a roster that fails this validation.

#### Scenario: Rejecting a roster with no developer
- **WHEN** an operator attempts to save a roster with zero agents whose
  `role` is `"developer"`
- **THEN** the save is rejected
- **AND** the operator sees the same message `AgentRoster`'s validator
  raises for a missing developer
- **AND** `roundtable.toml` is not modified

#### Scenario: Rejecting a duplicate agent name
- **WHEN** an operator attempts to save a roster containing two agents with
  the same `name`
- **THEN** the save is rejected with the duplicate-name message
  `AgentRoster`'s validator raises
- **AND** `roundtable.toml` is not modified

### Requirement: Roster save preserves unrelated config

A roster save SHALL rewrite only the `roster` field of the workspace's
`RoundtableConfig` and SHALL preserve every other top-level field (today,
just `round_limit`) unchanged, unless the operator explicitly edited it in
the same session.

#### Scenario: round_limit survives an unrelated roster edit
- **WHEN** an operator edits an agent's `persona` and saves, without
  touching round-limit settings
- **THEN** the resulting `roundtable.toml` has the same `round_limit` value
  it had before the save

### Requirement: Roster save uses a held advisory lock, not check-then-write

A roster save SHALL acquire a non-blocking, process-death-safe OS advisory
lock (e.g. `flock`) on a `roundtable.lock` file beside `roundtable.toml`
before reading `roundtable.toml`, and SHALL hold that lock across the entire
read-validate-write sequence, releasing it only after the write completes or
validation/I/O fails. The write itself SHALL remain atomic (serialize to a
temp file in the same directory, then rename over the target); the lock is
what prevents two writers from racing to begin with, and atomicity alone is
not a substitute for it.

Lock ownership SHALL NOT be reclaimed by inspecting the lock file's age or
recorded process id. The OS advisory lock is the sole ownership and
crash-recovery mechanism: if the holding process dies, the OS releases the
lock automatically, and a new acquirer succeeds through the normal
non-blocking acquire — no separate staleness check is needed, and using one
to unlink or replace an in-use lock file risks a second writer proceeding
against a lock the first writer still legitimately holds. A staleness
duration (default 60s since the lock's recorded acquisition time) MAY be
surfaced to the operator as an advisory "this may be taking a while" hint or
to inform a retry/backoff policy, but SHALL NOT affect lock ownership. This
protocol assumes a POSIX advisory-lock-capable local filesystem; behavior on
network filesystems or Windows is out of scope this iteration.

A validation failure or I/O error during the locked sequence SHALL leave the
last-known-good `roundtable.toml` untouched, SHALL release the lock, and
SHALL surface the error to the operator.

#### Scenario: Second editor is told to retry, not raced
- **WHEN** editor session A holds the `roundtable.lock` advisory lock and is
  mid-save
- **AND** editor session B attempts to save a roster edit for the same
  workspace
- **THEN** session B's non-blocking lock acquisition fails immediately
- **AND** session B is told the roster is being edited elsewhere and must
  retry
- **AND** no attempt is made to write `roundtable.toml` from session B until
  it successfully acquires the lock

#### Scenario: A crashed holder's lock is released by the OS, not by age
- **WHEN** editor session A acquires the lock and then its process is killed
  before releasing it
- **AND** editor session B attempts to acquire the lock immediately
  afterward, before any staleness timeout would have elapsed
- **THEN** session B's acquisition succeeds, because the OS released the
  advisory lock when session A's process died
- **AND** no age- or PID-based check was needed or consulted to permit this

#### Scenario: An old but still-held lock is never broken by age
- **WHEN** editor session A has held the lock for longer than the
  configured staleness duration, actively performing a slow save
- **AND** editor session B attempts to save
- **THEN** session B's non-blocking acquisition still fails, because session
  A's process is alive and the OS lock is still held
- **AND** session B is told to retry, not permitted to write

### Requirement: Live event feed content and scope

The UI SHALL show, for the specification being viewed, a real-time,
filterable feed of the events actually recorded in
`SqliteEventStore`: `ArtifactDrafted`, `CritiqueSubmitted`,
`RevisionRequested`, `ConsensusDeadlocked`, `ConsensusReached`. This feed
SHALL be presented as a projection of recorded review events, not a
freeform inter-agent chat transcript; since no such transcript is
persisted, the UI SHALL NOT display or imply one exists. Each item SHALL
show its `event_type`, `emitter`, `timestamp`, and its type-specific
payload (e.g. a `CritiqueSubmitted` item shows its `finding`'s
`target_section`, `severity`, `description`, and `suggested_patch`). The
feed SHALL support filtering by `emitter`, `event_type`, round number, and
keyword within `description`/`content` fields.

#### Scenario: A critique finding renders its full payload
- **WHEN** a `CritiqueSubmitted` event is recorded for the viewed
  specification
- **THEN** the feed shows an item with that event's `emitter`, `timestamp`,
  and its finding's `target_section`, `severity`, `description`, and
  `suggested_patch` (or its absence, if `suggested_patch` is null)

#### Scenario: No chat transcript is fabricated
- **WHEN** an operator views the event feed for a specification with no
  recorded events beyond the five structured event types
- **THEN** the UI shows only those recorded events
- **AND** presents no freeform inter-agent chat transcript

### Requirement: Event grouping by round number, labeled as such

The UI SHALL group feed items by round using `CritiqueSubmitted.review_id`
for critiques and `discussion_id` for `RevisionRequested`,
`ConsensusDeadlocked`, and `ConsensusReached`. Because the runner sets both
fields to the round number rather than a globally unique identifier, the UI
SHALL label this grouping as round-number-based, not as a stable or unique
run/round identifier, and SHALL NOT present it as one.

#### Scenario: Round grouping is labeled, not asserted unique
- **WHEN** an operator views the event feed grouped by round
- **THEN** each group is labeled by its round number
- **AND** no group label or UI copy asserts that number is a globally
  unique identifier across runs

### Requirement: Run selection scoped to one continuous history per specification

Because `SqliteEventStore` is keyed by `specification_id` only and
`EventEnvelope` carries no `run_id`, the UI SHALL show one continuous event
history per specification — whatever `replay(specification_id)` returns, in
append order — and SHALL NOT offer selection among multiple distinct past
runs of the same specification.

#### Scenario: Two runs against the same specification appear as one history
- **WHEN** a specification has been reviewed twice, producing two
  overlapping sequences of round-numbered events in the store
- **THEN** the UI shows a single ordered event history for that
  specification, with no run-selection control

### Requirement: Run lifecycle status is two always-defined, independently-shown signals

The UI SHALL compute and display run lifecycle status as two orthogonal
signals for the viewed specification — an **outcome label**, derived
solely from the event tail, and a **connection health**, derived solely
from the live transport and event recency — and SHALL display both
simultaneously (e.g. outcome label as the primary state, connection health
as a secondary badge) rather than collapsing them into one field. Neither
signal is an authoritative process-completion signal except where noted
below; both SHALL be presented with a visually distinct, muted treatment
from a hard state indicator, except the terminal "consensus reached"
outcome label. Status (either signal) SHALL NEVER gate a roster-edit save
or any other write; roster saves are governed only by the advisory lock.

Every specification the UI can be pointed at SHALL have a well-defined
value for both signals at all times, including a specification for which
`replay` returns no events — there is no state this requirement leaves
undefined.

**Outcome label**, computed from `replay(specification_id)`:
- **not started**: `replay` returns no events. This covers a specification
  with no run yet — a brand-new specification, or one the UI is pointed at
  before its first draft — and is the only outcome label that applies when
  history is empty.
- **consensus reached**: at least one event exists and the last one is
  `ConsensusReached`. This is the one outcome label this requirement
  treats as reliably terminal, because `ReviewRunner.run` returns
  unconditionally immediately after recording it. Once shown, it SHALL
  remain displayed regardless of any later change in connection health.
- **deadlocked (may still be active)**: the last event is
  `ConsensusDeadlocked`. The UI SHALL NOT label this "complete," because
  `ReviewRunner.run` can block on human confirmation after recording a
  deadlock and, given a truthy confirmation, resume into another critique
  round without recording any event until that round's first
  `CritiqueSubmitted` lands — and the confirmation step itself is not
  recorded as an event, so the event tail alone cannot distinguish "the run
  ended here" from "the run is paused here awaiting a human." The UI SHALL
  label this state as ambiguous/possibly-active rather than as either
  "in progress" or "complete."
- **in progress (estimated)**: at least one event exists and the last one
  is not `ConsensusReached` or `ConsensusDeadlocked` (i.e. `ArtifactDrafted`,
  `CritiqueSubmitted`, or `RevisionRequested`).

**Connection health**, computed from the live transport (see the transport
requirement below) and, where applicable, event recency:
- **live**: the transport is connected, and either no event has been
  recorded yet or the most recent event arrived within the configured
  staleness timeout (default 30s, operator-configurable).
- **stale**: the transport is connected, at least one event has been
  recorded, and no new event has arrived within the staleness timeout.
  Staleness SHALL NOT be evaluated when zero events have ever been
  recorded — there is no event timestamp to measure staleness from, so an
  empty history is "live" or "disconnected" only, never "stale"; the
  "not started" outcome label alone covers that case.
- **disconnected**: the transport itself is down, regardless of event
  count or recency. This is evaluated independently of staleness and can
  co-occur with any outcome label, including "consensus reached."

**Composition**: connection health SHALL NOT override, hide, or be merged
into the outcome label. The two are shown together as independent facts
(e.g. "consensus reached" + "disconnected" is a valid, expected
combination once a completed run's viewer later loses its connection —
the completed outcome is not downgraded or replaced by the transport
state). "not started" may co-occur with any connection health value (e.g.
a UI that fails to connect before any run has begun shows "not started" +
"disconnected," not "stale").

#### Scenario: A specification with no recorded run shows "not started"
- **WHEN** `replay` returns no events for the viewed specification
- **THEN** the UI shows the outcome label "not started"
- **AND** does not show "stale," "in progress," or any other outcome label

#### Scenario: An idle new specification is not shown as stale
- **WHEN** `replay` returns no events for the viewed specification
- **AND** the live transport is connected
- **THEN** the connection health is shown as "live," not "stale," because
  staleness is not evaluated with zero recorded events

#### Scenario: Consensus is shown as reliably terminal
- **WHEN** the last recorded event for a specification is `ConsensusReached`
- **THEN** the UI shows the outcome label "consensus reached"

#### Scenario: Consensus reached is not replaced by a later disconnect
- **WHEN** the outcome label for a specification is "consensus reached"
- **AND** the live connection subsequently drops
- **THEN** the UI continues to show the outcome label "consensus reached"
- **AND** additionally shows the connection health "disconnected"
- **AND** does not replace, hide, or downgrade the "consensus reached"
  label because of the disconnect

#### Scenario: Deadlock is shown as ambiguous, not complete
- **WHEN** the last recorded event for a specification is
  `ConsensusDeadlocked`
- **THEN** the UI shows the outcome label "deadlocked (may still be
  active)"
- **AND** the UI does not present this as a completed run

#### Scenario: A deadlocked outcome can be shown alongside a stale connection
- **WHEN** the outcome label for a specification is "deadlocked (may still
  be active)"
- **AND** no new event has arrived within the staleness timeout while the
  transport remains connected
- **THEN** the UI shows both the outcome label "deadlocked (may still be
  active)" and the connection health "stale," without either one replacing
  the other

#### Scenario: A resumed round after deadlock updates status without a resume event
- **WHEN** a run's last recorded event is `ConsensusDeadlocked`, and the
  operator has been shown the ambiguous deadlock status
- **AND** the runner subsequently resumes (human confirmation was truthy)
  and records a new `CritiqueSubmitted` event for the next round
- **THEN** the UI's outcome label transitions to "in progress (estimated)"
  once that event is delivered, with no dedicated resume event required

#### Scenario: Status never blocks a roster save
- **WHEN** the viewed specification's outcome label is "in progress
  (estimated)"
- **AND** an operator saves an unrelated roster edit
- **THEN** the save proceeds, gated only by the advisory lock, and the
  UI does not block or warn the save away because of either status signal

### Requirement: Artifact version browser shows labeled summaries only

The UI SHALL list every `ArtifactDrafted` event for the viewed
specification as one version, in append order, showing its `version_id`
(short SHA), `emitter`, `timestamp`, and its `content` field. The UI SHALL
label `content` as a reviewer-facing summary, not the complete artifact,
regardless of review phase, per `ArtifactDrafted`'s own documented contract.
The UI SHALL NOT resolve `version_id` to full artifact content or offer a
diff view; neither `ArtifactDrafted` nor the store carries the path or
workspace/repository root needed to do so deterministically.

#### Scenario: A version lists its summary, labeled as such
- **WHEN** an `ArtifactDrafted` event is recorded
- **THEN** the version browser adds an entry showing its `version_id`,
  `emitter`, `timestamp`, and `content`
- **AND** the `content` is labeled as a summary, not the full artifact

#### Scenario: No diff or full-content resolution is offered
- **WHEN** an operator views the version browser
- **THEN** no control offers to resolve a version to its full file content
  or to diff two versions

### Requirement: Real-time transport, ordering, and deduplication

The UI SHALL receive event updates via a push transport (WebSocket or
Server-Sent Events) from a backend process that tails
`SqliteEventStore.replay` for the viewed `specification_id`; polling
`replay` on an interval is an acceptable fallback implementation of the same
contract, not a different one. Because `EventStoreProtocol.replay` returns
full history in append order with no cursor, the backend SHALL replay full
history on each poll/connect and diff it against what it has already sent
downstream by `event_id`, rather than assuming a store-level cursor exists.
The client SHALL discard any event whose `event_id` it has already
rendered, so an at-least-once delivery transport cannot double-render an
item. An event SHOULD reach the UI within 2 seconds of being appended to
the store under normal operation. If the backend connection drops, the UI
SHALL retain the last-received event list, mark the connection
disconnected, and retry with backoff, without clearing previously rendered
events.

#### Scenario: A duplicate delivery is not double-rendered
- **WHEN** the backend delivers the same `event_id` to the client twice
  (e.g. across two poll cycles)
- **THEN** the feed renders exactly one item for that `event_id`

#### Scenario: Connection loss preserves prior events
- **WHEN** the live connection to the backend drops after events have been
  rendered
- **THEN** the UI keeps showing every previously rendered event
- **AND** marks the run status as disconnected
- **AND** retries the connection with backoff
