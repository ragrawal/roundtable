# Design

## Context

See `proposal.md` — Why for motivation. Requirements live in
`specs/{project-scaffolding,agent-orchestration,spec-review-rounds,event-store}/spec.md`.

Constraints that shape the approach:

- **`roundtable` is greenfield.** `src/roundtable/` holds only
  `__init__.py` and `py.typed`; `pyproject.toml` declares
  `dependencies = []`. There is no existing architecture to fit into, but
  `AGENTS.md` sets binding conventions: domain-model-first with thin
  controllers, Pydantic for validation-heavy models, fail fast with no
  defensive defaulting, `Field(..., description=...)` on every model field,
  Google-style docstrings on public API, and each tool's config in its own
  file rather than `pyproject.toml`.
- **herdr `0.9.1` is the verified contract.** The installed CLI emits JSON on
  stdout (`{"id": ..., "result": {...}}`) for `api snapshot`, `agent list`,
  and friends. Relevant surface, confirmed against `--help`:
  - `herdr pane split [--pane <ID>] [--direction right|down] [--cwd <PATH>] [--env K=V]`
  - `herdr agent start <NAME> --kind <KIND> --pane <ID> [--timeout <MS>]`
  - `herdr agent prompt <TARGET> <TEXT> [--wait] [--until <STATUS>] [--timeout <MS>]`
  - `herdr agent wait <TARGET> [--until <STATUS>] [--timeout <MS>]`
  - `herdr agent read <TARGET> [--source visible|recent|recent-unwrapped|detection] [--lines N]`
  - `herdr pane close <PANE_ID>`
  - Agent states are exactly `idle | working | blocked | done | unknown`,
    matching the states the proposal assumed.
- **Two corrections to the source specification**, both confirmed against the
  installed binary:
  1. `agent start` requires an **existing pane already at an interactive
     shell prompt** — it does not create one. The wrapper must `pane split`
     first, then `agent start` into the returned pane id. The architecture is
     therefore pane-allocation-then-agent-start, not a single spawn call.
  2. herdr runs as a persistent server with named sessions
     (`herdr --session <name>`); the Python package does not "spawn herdr" as
     a child it owns. It attaches to a running server, or starts one, and
     addresses panes within a session. This matters for teardown: closing our
     panes must not take down a session the user is also using. (This very
     Claude Code session is running as pane `w8:p1` in workspace `w8`.)
- **Testing.** `pytest.ini` enforces `--cov=roundtable` with an 80% floor in
  `.coveragerc`, and the suite is pytest-bdd with step definitions in
  `tests/bdd/actions/*` re-exported through `tests/bdd/conftest.py`. CI runs
  `uv run poe check --full`.

## Goals / Non-Goals

**Goals:**

- Isolate herdr's CLI behind one seam, so a herdr version bump touches one
  module and the test suite needs no live herdr server.
- Make the review lifecycle a pure, synchronously-testable state machine —
  decisions about consensus, revision, and deadlock must be assertable
  without any subprocess or agent.
- Validate agent-produced data at the process boundary, before it reaches
  storage, per the event-store spec's "validation precedes persistence".
- Let a spec review complete and stop on its own; a code review is a
  separate, later invocation that resolves its own starting context rather
  than something the spec phase chains into automatically.

**Non-Goals:**

- A long-running daemon, HTTP API, or TUI of our own. herdr is the UI.
- Concurrency beyond what reviewer parallelism needs. Reviewer turns overlap;
  nothing else does.
- Recovering a partially-completed run in-process after the process has
  exited or crashed. A crashed run is reconstructable from the event log (per
  spec), but resuming it is future work. This is distinct from the deadlock
  pause in Decision 10, which keeps the same process alive and blocked — there
  is no exit and no separate resume command to design for that case.

## Decisions

### 1. herdr access via subprocess + JSON, not a socket client

`herdr api schema` exposes a socket API, and speaking it directly would avoid
process-spawn overhead. We will still shell out to the `herdr` CLI and parse
its JSON stdout.

*Why:* the CLI is the documented, stable, version-negotiated surface; the
socket protocol is versioned (`"protocol": 22` in the snapshot) and undocumented
for third parties. Per-call overhead is single-digit milliseconds against agent
turns measured in tens of seconds — the wrong thing to optimize. *Alternative
considered:* a native socket client. Rejected as premature coupling to an
internal protocol; the `HerdrClient` seam leaves it as a drop-in replacement
later.

The client will assert a supported `herdr` major version at `init` and at run
start (`project-scaffolding`'s prerequisite requirement), and raise a typed
error per failure mode herdr names — `agent_blocked`, `agent_prompt_stalled`,
`timeout` — rather than a generic `CalledProcessError`. Fail fast and loud, per
`AGENTS.md`.

### 2. Agents return results as JSON files; terminals are never parsed

Each agent turn gets a round directory under `.roundtable/scratch/<round>/`,
which `init` adds to `.gitignore` (per `project-scaffolding`'s workspace
layout and `agent-orchestration`'s ephemeral-scratch requirement). The
agent's prompt instructs it to write its result to a named path there; the
framework waits for the terminal state, then reads and validates that file.
Scratch directories are left on disk after the round, not deleted — cheap
disk usage traded for a crash's diagnostic trail surviving past the process
that hit it.

*Why:* the alternative — scraping `agent read` output — means parsing a TUI
whose rendering is not a stable contract, with ANSI escapes, reflow, and
scrollback truncation. A state machine built on that is unfixable when it
breaks. Terminal snapshots are still captured, but only as diagnostic context
attached to a failure report, which is what `agent-orchestration`'s
missing-result scenario specifies. *Alternative considered:* having agents emit
structured output on a side channel — herdr offers none per-agent.

### 3. Event store as append-only JSONL, one file per specification

Events append as one JSON object per line under the workspace's store
directory, keyed by specification id.

*Why:* it satisfies every event-store requirement — append order is file
order, replay is a sequential read, restart-durability is filesystem
durability, and there is no mutation API to expose — while staying diffable and
greppable by the human reviewing the run. Committing it to Git alongside the
drafts gives the traceability the proposal asks for. *Alternative considered:*
SQLite. Better for indexed queries over many runs, but it adds a schema
migration concern, makes "append-only" a discipline enforced by convention
rather than by structure, and produces a binary blob in Git. Revisit if
cross-run querying becomes a real need.

Uniqueness of event ids (per spec) is enforced by an in-memory set of ids seen
when the store is opened — O(n) on open, O(1) per append, with n bounded by one
specification's run history.

`append` SHALL be safe under `ReviewRunner`'s concurrent reviewer threads
(Decision 5): a `threading.Lock` held for the validate-then-write-one-line
critical section serializes concurrent callers, satisfying `event-store`'s
concurrent-append-safety requirement without changing the file format. The
store is exposed behind a small `EventStoreProtocol` (`append`, `replay`,
`latest_of_type`) rather than a concrete class reference throughout
`orchestration` and `review-command` — `latest_of_type` is what
`review code`'s consensus lookup (Decision 9) calls. *Why a protocol:* it's
the seam a future SQLite/DuckDB backend would need for indexed cross-run
queries, without `ReviewRunner` importing anything JSONL-specific; JSONL
stays the only implementation for now.

### 4. A `RoundtableEvent` discriminated union, validated once at the boundary

Pydantic v2 models: a shared envelope base plus one payload model per event
type, combined as a discriminated union on `eventType`, configured with
`extra="forbid"`.

*Why:* `extra="forbid"` is what turns "an agent hallucinated a field" into a
rejection rather than a silently-dropped value — required by the
unexpected-extra-field scenario. A discriminated union gives the
unrecognized-type rejection for free, with error messages that name the
offending field, which several spec scenarios require. Severity is a
`StrEnum` (`blocking | major | minor | info`) so an out-of-set severity is
rejected by the same mechanism.

The draft payload type is named `ArtifactDrafted`, not `SpecDrafted`: once
`review-command` (Decision 9) reuses the same event schema for the code
phase, a spec-flavored name for a payload that may carry a code-phase diff
summary would be misleading. `content` is documented as a reviewer-facing
summary rather than the authoritative multi-file state, which the payload's
version identifier (a Git commit) already references — see `event-store`'s
typed-payloads requirement.

### 5. The review lifecycle is a pure state machine

`orchestration` splits in two: a pure `ReviewRound` domain model that maps
(current draft, collected critiques, round number, round limit) to a decision
— `ReachedConsensus | RequestRevision | Deadlocked` — and a thin `ReviewRunner`
that performs the I/O (prompt agents, read files, commit, append events).

*Why:* this is `AGENTS.md`'s domain-model-first/thin-controller rule applied to
the hardest-to-test part of the system. Every consensus, round-limit, and
deadlock scenario in `spec-review-rounds` becomes a table-driven test over the
pure function, with no fakes at all. *Alternative considered:* folding the
decision logic into the runner's loop. Rejected — it would make the round-limit
and severity-gating scenarios reachable only through an orchestration fake.

Reviewer turns run in parallel via `ThreadPoolExecutor`. Threads, not asyncio:
the work is blocking subprocess calls, the fan-out is the roster size, and
threads keep the runner synchronous and therefore straightforward to test.
Each thread's `agent prompt --wait` call carries the turn timeout from
`agent-orchestration`'s "Prompted turns are awaited to a terminal state"
requirement as a hard subprocess-level timeout (`subprocess.run(..., timeout=)`),
not merely a state-polling deadline — a stalled herdr call can only block its
own worker thread until that timeout fires, never the pool, since the
timeout is what guarantees the blocking call returns at all.

`ReviewRound`'s deadlock trigger stays purely round-limit-based: round number
at or past the configured limit with a `blocking` critique still outstanding.
Detecting that two reviewers' `blocking` critiques are mutually irreconcilable
before the limit — as opposed to merely both targeting the same section, which
says nothing about whether they agree — needs semantic comparison of critique
text that a pure, table-testable function over structured fields cannot do;
see Open Questions.

### 6. Teardown closes only panes we allocated

The runner records the pane ids it created and closes exactly those, skipping
panes retained for deadlock escalation. It never closes a pane it did not
create.

*Why:* see Context correction (2) — the user's own session shares the herdr
server. Teardown runs in a `finally` that collects rather than raises, so a
close failure is reported as a secondary warning and cannot mask the run's real
outcome, as `agent-orchestration` requires.

### 7. `typer` for the CLI

*Why:* type-hint-driven commands fit a pyright-strict codebase, and it gives
`--help` and exit codes without hand-rolling `argparse`. Deadlock's
distinguishable non-zero status (per spec) becomes a dedicated exit code —
`0` consensus, `2` deadlock, `1` orchestration failure. *Alternative
considered:* stdlib `argparse` to keep `dependencies = []` — rejected;
`AGENTS.md` prefers a deliberate, comprehensive dependency over a workaround,
and Pydantic is already a required dependency.

### 8. `init`'s roster and round-limit collection is an interactive prompt loop, testable via scripted stdin

`init` prompts for agent count, then per-agent name/role/focus-prompt/kind,
then the round limit, using Typer/Click's prompt helpers (`click.prompt`,
with `type=click.Choice` for the prepopulated role and kind lists plus
free-text fallback). When `roundtable.toml` already exists, its parsed
values seed each prompt's `default=`, so pressing enter reproduces the
existing configuration.

Role and focus prompt are collected as two prompts, not one: a
`ROLE_FOCUS_PROMPTS: dict[str, str]` constant maps each predefined role
(`developer`, `product manager`, `senior engineer`, `security reviewer`,
`qa engineer`) to its canned focus-prompt text. After the role prompt, the
focus-prompt question's `default=` is looked up from that mapping when the
role matched a predefined entry, and is `None` (forcing entry, no default)
when the role was custom text outside the mapping.

*Why:* Click's prompt helpers already handle default-echoing, retry-on-invalid,
and free-text-outside-the-choice-list, so this needs no hand-rolled input loop.
Testability follows for free: `click.testing.CliRunner(...).invoke(app, input="3\ndeveloper\nclaude\n...")`
drives the whole flow deterministically without a real TTY, which is how the
`project-scaffolding` BDD scenarios (interactive configuration, prepopulated-list
and custom-entry, pre-population from an existing file) get exercised. *Alternative
considered:* a `--roster-file`/flags-only non-interactive mode. Deferred — no
scenario in `project-scaffolding` currently asks for unattended `init`, and
`CliRunner`'s scripted stdin already makes the interactive path scriptable for
tests, but real unattended use (CI, scripted setups) shouldn't have to fake a
TTY session: `init` also accepts a config-file path (`project-scaffolding`'s
non-interactive requirement) that supplies the roster and round limit
directly, skipping every prompt. The same `RoundtableConfig` model validates
both paths, so a non-interactive roster fails the same constraints an
interactive one would.

### 9. Spec and code phases share the round machine and event schema via a compound specification id

`review spec <id> ...` and `review code <id>` both drive the same
`ReviewRound`/`ReviewRunner` pair from Decision 5 and the same event schema
from Decision 4. What differs is the specification id each phase's events
and Git commits are keyed under: the spec phase uses `<id>`, the code phase
uses a derived id such as `<id>:code`. `review code` resolves its starting
context by replaying `<id>`'s event log for the latest `ConsensusReached`
event and reading the Git state it names; it refuses to start if no such
event exists.

*Why:* this reuses every existing piece — round decision logic, event
validation, replay, Git commit-per-version — with no new schema and no
special-casing in the store, which stays a generic per-id JSONL log. Keying
the two phases under related-but-distinct ids keeps `event-store`'s replay
requirement ("replay excludes events belonging to other specifications")
doing exactly the isolation work `review-command`'s resumability needs, for
free. *Alternative considered:* a single id with a `phase` field on every
event. Rejected — it would require every existing event type and the replay
requirement to become phase-aware, where a derived id needs neither.

The spec phase's initiating build description (inline or from a context
file) is a CLI/prompt-construction input, not a stored event field: it
shapes the first drafting prompt but the resulting `ArtifactDrafted` event
already captures what the developer agent produced from it, which is what
`spec-review-rounds`' reconstructability requirement asks for. Keeping it
out of the event schema avoids a conditionally-present field that only the
very first draft event of a spec phase would use.

### 10. Deadlock resolution blocks the process rather than exiting for a `--resume` flag

Two shapes were possible for human escalation on deadlock: (a) block the
running process on a confirmation prompt after reporting attach instructions,
resuming in-process once the human confirms; or (b) exit non-zero and require
a separate `roundtable review --resume <id>` invocation later. We're building
(a).

*Why:* the contested agents' panes are only meaningfully attachable while the
process that started them, and herdr's view of them, is still alive — exiting
throws that liveness away for no benefit, since the human is expected to
intervene within the same sitting, not days later. Blocking is a single
`click.confirm`-style prompt in `ReviewRunner`'s deadlock path: report the
attach instructions (per `spec-review-rounds`), then block on confirmation,
then either start a new critique round against the current draft or exit
recording the deadlock, per that spec's escalation requirement. *Alternative
considered:* the `--resume` flag. Rejected — it would need a second code path
for reattaching to already-running panes (or restarting agents mid-conversation,
losing their context), for a scenario (a human resolving a live disagreement
across two separate invocations of the CLI) that isn't the one this framework
targets; the panes and the process's in-memory state already agree on what's
contested, so tearing that down just to rebuild it is pure cost.

## Risks / Trade-offs

- **herdr's CLI or JSON shape changes across versions** → The whole surface
  sits behind `HerdrClient`; a supported major-version range is asserted at
  `init` and run start, failing with the detected-vs-supported versions rather
  than misbehaving mid-run. Pin the verified version (`0.9.1`) in the
  contract tests' fixtures.
- **Agents ignore the "write your result to this path" instruction** →
  Treated as a first-class failure mode with a named error and a terminal
  snapshot for diagnosis, not an exception. Prompt templates and the result
  schema are versioned together so a schema change forces a prompt review.
- **Scraped terminal snapshots are the only diagnostic when an agent
  misbehaves** → Accepted. Decision 2 trades diagnostic richness for a
  trustworthy control path; the snapshot is attached to failures so the human
  still has the evidence.
- **Reviewer parallelism makes runs nondeterministic in wall-clock order** →
  Event ordering is per-specification append order, not causal ordering across
  reviewers. Critique events carry the draft version they target, so replay
  groups them by round regardless of arrival order.
- **Round-limit default of 3 may be wrong in practice** → It is configuration,
  not a constant, and the spec only requires a bound of at least one.
- **Cost and latency: each round is `1 + reviewers` agent turns** → Out of
  scope to optimize now; the round limit is the cap. Worth revisiting once
  there is real usage data.
- **Committing the event log to Git couples run history to repo history** →
  Accepted deliberately; it is the traceability the proposal asks for. The log
  is JSONL specifically so those commits stay reviewable.

## Migration Plan

Not applicable — greenfield package with no existing users, no persisted data
to migrate, and no public API to keep compatible. Two in-repo replacements,
both covered in `tasks.md`:

- `pyproject.toml` moves from `dependencies = []` to the runtime set
  (`pydantic`, `pydantic-settings`, `typer`) and gains a `[project.scripts]`
  entry for `roundtable`.
- `tests/bdd/example/` is the scaffold's placeholder feature; it is removed
  once the first real capability feature lands, per its own docstring.

Rollback is `git revert` plus `uv sync`.

## Open Questions

- ~~Which reviewer personas beyond product-management and security earn a
  seat?~~ Resolved: `init`'s role prompt offers a prepopulated list (developer,
  product manager, senior engineer, security reviewer, QA engineer) plus a
  custom-entry fallback, so any persona is a per-run choice, not a code change.
- **Should the code phase support reviewing only the files a revision round
  touched, rather than the whole implementation each round?** Out of scope
  for now — `review-command` only requires that the code phase start from
  the approved spec; the round machine already treats "the artifact" opaquely,
  so scoping what's re-reviewed per round is a `ReviewRunner` refinement, not
  a spec change, if it turns out to matter at real implementation sizes.
- **Whether `major`-severity findings should eventually gate consensus.**
  Currently advisory by spec; if usage shows `major` findings being lost, that
  is a spec change and a new proposal, not a deferred implementation detail.
- **Should the framework detect mutually irreconcilable `blocking` critiques
  and declare a deadlock before the round limit, rather than always spending
  the remaining rounds?** Deliberately not implemented (see Decision 5):
  reviewers targeting the same section doesn't mean they disagree, and telling
  disagreement apart from independent-but-compatible objections needs
  semantic comparison of critique text, which breaks the pure, table-tested
  `ReviewRound` function this design is built around. Revisit only if
  round-limit exhaustion on genuinely irreconcilable critiques turns out to be
  common enough in practice to justify that cost.
