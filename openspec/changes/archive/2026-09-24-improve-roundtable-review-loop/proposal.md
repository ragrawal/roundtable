# Proposal

## Why

Dogfooding the framework surfaced three gaps between how a review run
behaves and what an operator watching it actually needs: consensus lets
substantive (non-`blocking`) findings slide through unresolved, every agent
pane vanishes the instant a run ends even though the operator often wants to
keep inspecting or nudging the agents afterward, and a run is silent from
launch to its single final result line, giving no sense of what's happening
during the minute-plus it takes real agents to draft and critique. Separately,
the event store's one-JSONL-file-per-specification layout makes it awkward to
query or inspect a run's history as a whole. This change addresses all four.

## What Changes

- **Consensus requires every finding resolved, not just `blocking` ones**:
  `major` and `minor` critiques now gate consensus the same way `blocking`
  ones do — any of the three raised in a round requests a revision (or, once
  the round limit is exhausted, a deadlock). `info` findings remain purely
  advisory and never gate consensus.
- **Panes are never auto-closed at the end of a run**: `ReviewRunner` stops
  tearing down agent panes when a run ends in consensus, deadlock, or an
  incomplete round. Every pane the framework allocated for the run stays
  open and attachable so the operator can keep inspecting or interacting
  with an agent after the run finishes. Rolling back panes opened partway
  through a *failed pane allocation* (before any agent has done a turn) is
  unaffected — those panes never participated in a review and are still
  closed as part of that failure path.
- **Progress is narrated as the run proceeds**: the runner reports each
  meaningful step as it happens — round start, "developer is drafting" /
  "developer is revising", "reviewers are critiquing the draft", each
  reviewer's result as it arrives (e.g. `senior-engineer raised 2 major
  findings`), and the round's outcome (consensus / revision requested /
  deadlock) — instead of only printing the run's single final line.
- **BREAKING: event store moves from one JSONL file per specification to a
  single SQLite database per workspace.** `JsonlEventStore` is replaced by a
  SQLite-backed store that implements the same `EventStoreProtocol`
  (`append`, `replay`, `latest_of_type`) so `ReviewRunner` and
  `review_command` are unaffected, but the on-disk format changes:
  `.roundtable/events/<specification_id>.jsonl` files are replaced by a
  single `.roundtable/events/events.db`, with every event type stored as a
  row (specification id, event type, timestamp, emitter, and payload) rather
  than a line in a per-spec file. There is no migration path for existing
  `.jsonl` event logs — this repo's own dogfood workspace's event history
  will need to be regenerated. Round-scratch result files
  (`.roundtable/scratch/<round>/<agent>.json`) are unaffected: they remain
  ephemeral, gitignored JSON files, not part of the durable event log.

## Capabilities

### New Capabilities
- `review-progress-reporting`: the narrated, step-by-step status output a
  review run produces as it progresses — what gets reported, when, and in
  what form — distinct from the final outcome line `review-command` already
  specifies.

### Modified Capabilities
- `spec-review-rounds`: consensus gating changes from "no `blocking`
  critique raised" to "no `blocking`, `major`, or `minor` critique raised";
  `info` critiques remain advisory-only.
- `agent-orchestration`: the "Run teardown" requirement changes from
  releasing every pane not needed for escalation to never automatically
  releasing any pane once a run has allocated and used them for a turn.
- `event-store`: the storage backend changes from one append-only JSONL file
  per specification to a single SQLite database per workspace; the store's
  ordering, replay, and validation-at-the-boundary guarantees are preserved.

## Impact

- **`src/roundtable/store.py`**: `JsonlEventStore` is replaced by a
  SQLite-backed implementation of `EventStoreProtocol` (name TBD in design,
  e.g. `SqliteEventStore`). New dependency: none required — `sqlite3` is in
  the Python standard library.
- **`src/roundtable/workspace.py`**: `events_root()`/workspace scaffolding
  changes from creating a directory of `.jsonl` files to creating (or
  opening) a single `.roundtable/events/events.db` SQLite file.
- **`src/roundtable/orchestration.py`**: `ReviewRunner.teardown()` behavior
  changes (no automatic close-on-completion); `ReviewRound.decide`'s
  blocking-severity check widens to `{blocking, major, minor}`; new
  progress-reporting calls are threaded through `run()`, `run_draft()`,
  `run_critique_round()`, and `run_revision()`.
- **`src/roundtable/review_command.py`**: wires a progress reporter (e.g. to
  `click.echo`) into `ReviewRunner`, matching how the CLI is already the
  layer that prints the run's final outcome.
- **Tests**: existing unit and BDD suites that assert `major`/`minor`
  critiques reach consensus, or that panes close after a run, need updating
  to the new behavior; `store.py`'s test suite moves from asserting JSONL
  file contents to asserting SQLite row contents; new BDD coverage for
  progress reporting. Coverage must stay above the 80% floor.
- **Not in scope**: migrating existing `.jsonl` event histories into SQLite;
  moving round-scratch result files into SQLite; changing how `info`-severity
  critiques are handled; a pane-close/cleanup command for panes now left
  open indefinitely (operators use herdr directly today).
