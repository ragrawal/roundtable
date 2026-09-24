# Design

## Context

`ReviewRunner.run()` (`src/roundtable/orchestration.py`) drives the whole
review lifecycle: `allocate_panes()` → `run_draft()` → a loop of
`run_critique_round()` / `ReviewRound.decide()` / `run_revision()` → a
`finally: self.teardown(retain=retain_agents)` that always runs. `decide()`
is a pure function; it currently filters critiques with
`finding.severity == Severity.BLOCKING` to decide whether a round gates
consensus. The CLI (`review_command.execute_review`) only prints one line at
the very end (`Consensus reached...` / `Deadlocked on...`) plus any teardown
warnings — nothing during the run itself.

The event store already has two implementations side by side in
`src/roundtable/store.py`: `JsonlEventStore` (currently wired up as the
default in `review_command.execute_review`) and an already-written but
**unused** `SqliteEventStore` (single `events` table: `event_id`,
`specification_id`, `event_type`, `emitter`, `timestamp`, a per-specification
`sequence` column for ordering, and `payload` holding the full validated
event as JSON, indexed on `(specification_id, sequence)`). `workspace.py`
already has `events_db_path()` alongside `events_root()`. Neither is
referenced anywhere outside `store.py`/`workspace.py` yet — this change
finishes wiring it in rather than building it from scratch. See
`proposal.md` - Why for the motivation behind all four changes.

## Goals / Non-Goals

**Goals:**
- Widen the consensus gate from "no `blocking` critique" to "no `blocking`,
  `major`, or `minor` critique", per `spec-review-rounds`'s delta.
- Stop calling any automatic pane-close path once a run has started at
  least one agent turn, per `agent-orchestration`'s delta.
- Give `ReviewRunner` a way to emit step-by-step progress that
  `review_command` renders to the terminal, per the new
  `review-progress-reporting` capability.
- Make `SqliteEventStore` the default store `execute_review` constructs, and
  retire `JsonlEventStore`, per `event-store`'s delta.

**Non-Goals:**
- Migrating existing `.jsonl` event histories (including this repo's own
  dogfood `.roundtable/events/ui.jsonl`) into SQLite.
- Moving round-scratch result files (`.roundtable/scratch/<round>/<agent>.json`)
  into SQLite — they stay ephemeral, gitignored files.
- A command to manually close panes left open after a run — out of scope
  per the proposal; operators use herdr directly.
- Making the consensus-gating severity set configurable — this change makes
  it `{blocking, major, minor}` unconditionally.

## Decisions

**Widen the gate, don't add a config knob.** `ReviewRound.decide` changes its
filter from `severity == BLOCKING` to `severity != INFO` (equivalently,
`severity in {BLOCKING, MAJOR, MINOR}`). Considered making the gating set
configurable in `roundtable.toml` instead of a hardcoded change — rejected as
premature: the user asked for one fixed behavior, and a config knob adds a
validation and documentation surface for a need that hasn't materialized yet.
`ReviewRound._build_deadlock`'s existing logic (targets the first non-advisory
finding) is unaffected; only what counts as "non-advisory" changes.

**Remove teardown entirely rather than making it a no-op.** `ReviewRunner`
currently has `teardown()`, the `TeardownWarning` dataclass, and a
`finally: self.teardown(retain=retain_agents)` in `run()`, whose result is
returned to and printed by `execute_review`. Since no pane is ever
automatically closed once a run has started a turn, `teardown()` has nothing
left to do in that path, so it is deleted along with `TeardownWarning`, and
`run()`'s return type simplifies from `tuple[RoundOutcome, tuple[TeardownWarning, ...]]`
to `RoundOutcome`. `execute_review`'s warning-printing loop goes with it.
Considered keeping `teardown()` dormant, unwired, for a possible future
manual close command — rejected as dead code; the proposal explicitly puts a
close command out of scope, and the method is trivial to resurrect from Git
history if that changes. `allocate_panes()`'s own rollback path (closing
panes opened partway through a *failed* roster startup, before any turn
happened) is untouched — it already closes panes directly, not through
`teardown()`, and that failure mode is explicitly excluded from the
"never auto-close" requirement.

**Progress reporting is a caller-supplied callback, matching the existing
`confirm` pattern.** `ReviewRunner` gains a `report: Callable[[str], None]`
field (defaulting to a no-op), called at each point the
`review-progress-reporting` spec names: round start, draft/revise start,
critique start, each reviewer's result as its turn completes, and the
round's outcome. `execute_review` wires `report=lambda message: click.echo(message)`.
This mirrors how `confirm: Callable[[], bool] | None` already crosses the
domain/CLI boundary in this codebase (`AGENTS.md`'s thin-controller
convention: `ReviewRunner` stays free of direct I/O against the terminal,
`review_command` supplies it). Considered having `ReviewRunner` return a
stream/iterator of status events for the CLI to consume — rejected as
unnecessary indirection for a callback that's already the established
pattern here, and it would complicate the synchronous, blocking control flow
`run()` already has.

**Report each reviewer's result as its turn completes, not after the whole
round.** `run_critique_round` currently loops `for future, reviewer in
futures.items(): future.result()`, which iterates in submission (roster)
order, so waiting on an earlier future can delay reporting a later reviewer
that actually finished first. Switching to
`concurrent.futures.as_completed(futures)` reports (and records the
`CritiqueSubmitted` events for) each reviewer in true completion order,
matching the "as it arrives" wording in `review-progress-reporting`'s spec.
This does not change `run_critique_round`'s return value, which is already
re-assembled in roster order (`tuple(results[reviewer.name] for reviewer in
reviewers)`) for `ReviewRound.decide`, so decision logic is unaffected —
only the order in which progress is reported and events are appended
changes, and event order is already tracked by the store's own `sequence`
column, not wall-clock position.

**Finish wiring the already-written `SqliteEventStore`, don't design a new
one.** `execute_review`'s default store construction changes from
`JsonlEventStore(events_root(workspace_root))` to
`SqliteEventStore(events_db_path(workspace_root))`. `JsonlEventStore` is
deleted from `store.py` (the proposal is a replacement, not a
parallel option), and `store.py`'s module docstring updates accordingly.
`store.py`'s existing `JsonlEventStore` test suite is ported to
`SqliteEventStore` — same `EventStoreProtocol`, so most test bodies carry
over; assertions on raw file/line contents become assertions on rows read
back through the store's own `replay`/`latest_of_type`, or, where a test
specifically wants to check the physical encoding, direct `sqlite3` queries
against the `.db` file in place of reading `.jsonl` lines.

## Risks / Trade-offs

- **[Widening the gate to `major`/`minor` makes deadlocks much more common
  in practice]** → The existing `round_limit` (default 3, configurable) is
  the safety valve and is unchanged; an operator who finds deadlocks firing
  too readily can raise it in `roundtable.toml`. No code change needed to
  tune this.
- **[Panes never auto-close, so long/iterative dogfooding sessions
  accumulate open herdr panes]** → Explicitly accepted by the proposal
  (operators clean up via herdr directly); flagged here as a known ongoing
  cost, not a defect.
- **[`run()`'s return type change (`RoundOutcome` instead of a 2-tuple) is a
  breaking change to `ReviewRunner`'s public API]** → `execute_review` is
  the only call site in this codebase; both change together in the same
  commit.
- **[Reordering reviewer completion via `as_completed()` changes which
  `CritiqueSubmitted` events get appended first when reviewers finish out of
  roster order]** → Harmless: `replay()`'s ordering is driven by the store's
  own `sequence` column (assigned at append time), and `ReviewRound.decide`
  already re-sorts turns back into roster order before deciding — no
  consumer depends on roster-order event append.
- **[SQLite has no built-in cross-process writer coordination beyond file
  locking]** → No regression: `JsonlEventStore` never coordinated across
  processes either, and exactly one `roundtable review` process per
  workspace is the existing assumption. `SqliteEventStore.append()` already
  serializes within-process via its own `threading.Lock()`.

## Migration Plan

- No automated migration for existing `.jsonl` event logs, including this
  repo's own dogfood workspace's `.roundtable/events/ui.jsonl` — once
  `SqliteEventStore` is wired in as the default, that file is simply no
  longer read. Anyone who needs that history keeps the `.jsonl` file
  around for manual reference; `replay`/`latest_of_type` against it stop
  working since nothing constructs a `JsonlEventStore` anymore.
- Single-step rollout, no feature flag: this is pre-1.0 tooling with one
  operator (the project's own maintainer), so there's no compatibility
  window to preserve.

## Open Questions

- Now that any `major` or `minor` finding (not just `blocking`) gates
  consensus, is `round_limit`'s current default of 3 still the right
  default, or should it move up? This doesn't change any spec, decision, or
  task in this change — it's a tuning question best answered from real
  usage after this ships.
