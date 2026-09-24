# Tasks

## 1. Widen consensus gating to major/minor

- [x] 1.1 Change `ReviewRound.decide`'s blocking-findings filter to include `MAJOR` and `MINOR` alongside `BLOCKING` (excluding only `INFO`), and update its consensus/deadlock/revision-request construction to use the widened set consistently
- [x] 1.2 Update `tests/unit/test_orchestration.py` (and any other unit tests asserting the old blocking-only gate) to cover: only-`info` reaches consensus, a lone `major` blocks consensus, a lone `minor` blocks consensus, and mixed-severity critiques are all carried into the revision request — verify via `uv run pytest tests/unit/test_orchestration.py -v`
- [x] 1.3 Update `tests/bdd/spec_review_rounds/spec_review_rounds.feature` (and step definitions if needed) to add/adjust scenarios matching `specs/spec-review-rounds/spec.md`'s new "One major critique" / "One minor critique" scenarios — verify via `uv run pytest tests/bdd/spec_review_rounds -v`

## 2. Remove automatic pane teardown

- [x] 2.1 Delete `ReviewRunner.teardown()` and the `TeardownWarning` dataclass from `src/roundtable/orchestration.py`, and remove the `finally: self.teardown(...)` block and `retain_agents` bookkeeping from `run()`
- [x] 2.2 Change `ReviewRunner.run()`'s return type from `tuple[RoundOutcome, tuple[TeardownWarning, ...]]` to `RoundOutcome`, and update its docstring's `Returns`/`Raises` sections to state panes are never closed once a turn has started
- [x] 2.3 Update `review_command.execute_review` to drop the teardown-warning printing loop and adapt to `run()`'s new return value — verify by running `uv run roundtable review spec <id> ...` end to end and confirming no `Warning: could not close pane` output path remains reachable
- [x] 2.4 Update `tests/bdd/agent_orchestration/agent_orchestration.feature` and `tests/bdd/actions/agent_orchestration.py` (and `tests/unit/test_review_runner.py`) so consensus, deadlock, and incomplete-round scenarios all assert every allocated pane remains open — verify via `uv run pytest tests/bdd/agent_orchestration tests/unit/test_review_runner.py -v`

## 3. Add progress reporting

- [x] 3.1 Add a `report: Callable[[str], None]` field to `ReviewRunner` (default no-op), and call it at round start, draft start, revise start, critique start, each reviewer's result (name + finding counts by severity, including zero-finding), and round outcome (consensus/revision/deadlock with distinguishing detail), per `specs/review-progress-reporting/spec.md`
- [x] 3.2 Change `run_critique_round`'s result collection from `for future, reviewer in futures.items()` to `concurrent.futures.as_completed(futures)` so each reviewer's report fires in true completion order, while keeping the returned tuple in roster order
- [x] 3.3 Wire `report=lambda message: click.echo(message)` (or equivalent) in `review_command.execute_review`
- [x] 3.4 Add unit tests for `ReviewRunner`'s reported message sequence (round start before drafting, critique-start before reviewer prompts, one report per reviewer in completion order, outcome report matching the actual outcome) — verify via `uv run pytest tests/unit/test_review_runner.py -v`
- [x] 3.5 Add/extend BDD coverage asserting a reviewer that finishes first is reported before a slower reviewer in the same round — verify via `uv run pytest tests/bdd/agent_orchestration -v`

## 4. Switch the default event store to SQLite

- [x] 4.1 Change `review_command.execute_review`'s default store construction from `JsonlEventStore(events_root(workspace_root))` to `SqliteEventStore(events_db_path(workspace_root))`
- [x] 4.2 Delete `JsonlEventStore` from `src/roundtable/store.py` and update the module's docstring to describe `SqliteEventStore` as the sole implementation
- [x] 4.3 Port `JsonlEventStore`'s existing test suite in `tests/unit/test_store.py` (or equivalent) to exercise `SqliteEventStore` instead — same `EventStoreProtocol` behaviors (append, replay, latest_of_type, duplicate-event rejection, concurrent-append safety), replacing any raw `.jsonl` line assertions with `sqlite3` row assertions — verify via `uv run pytest tests/unit/test_store.py -v`
- [x] 4.4 Grep the codebase and tests for remaining `JsonlEventStore`/`.jsonl` event-store references (`events_root` usage for event files specifically, fixtures, docs) and update or remove them — verify via `grep -rn "JsonlEventStore" src/ tests/` returning no matches

## 5. Full verification

- [x] 5.1 Run `uv run poe check --full` and confirm lint, type-check, and the full test suite (with the 80% coverage floor) all pass
- [x] 5.2 Run `openspec validate improve-roundtable-review-loop --strict` and confirm it still reports valid
