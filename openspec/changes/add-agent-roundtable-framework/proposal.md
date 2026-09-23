# Proposal

## Why

Writing an OpenSpec change well requires adversarial review from several
perspectives — product framing, security, feasibility — but a single agent
session reviewing its own draft inherits its own blind spots and context. This
change builds `roundtable`: a framework that drafts an OpenSpec change in one
agent and critiques it in separate, context-isolated reviewer agents, so
critiques are genuinely independent rather than self-confirming, and every
draft, critique, and revision is recoverable after the fact.

## What Changes

- **`roundtable init` CLI command** that walks the user through an
  interactive setup: how many agents to configure, then per agent a name, a
  role chosen from a prepopulated list (developer, product manager, senior
  engineer, security reviewer, QA engineer, or a custom entry), a focus
  prompt describing what that agent pays attention to when reviewing — shown
  as an editable default drawn from the selected role when it's predefined,
  or authored by the user from scratch when the role is custom — and an
  agent kind — the LLM that runs it (claude, codex, or a custom entry) — and
  finally the maximum number of review rounds. When the target directory
  already has a `roundtable.toml`, its roster and round limit pre-populate
  every prompt's default, so re-running `init` is a guided edit rather than a
  blank slate. A `--config <path>` flag skips every prompt and reads the
  roster and round limit straight from a `roundtable.toml`-shaped file, for
  unattended setups. The command scaffolds an OpenSpec project layout, an
  initialized Git repository, an empty event store, and a gitignored
  round-scratch directory around the resulting roster, writing it all to
  `roundtable.toml`.
- **herdr-backed orchestration layer** that creates one pane per agent, starts
  an interactive agent in each, submits prompts, waits on agent state, and
  reads results. Panes give each agent a hard context boundary; herdr's own
  `idle`/`working`/`blocked`/`done` state tracking replaces any custom polling
  loop.
- **A review-round state machine**: the developer agent drafts a change, each
  reviewer agent critiques it in parallel, blocking critiques drive a revision
  round, and the round terminates in either consensus or a declared deadlock.
- **An append-only event store** with Pydantic-validated event payloads
  (`ArtifactDrafted`, `CritiqueSubmitted`, `RevisionRequested`,
  `ConsensusDeadlocked`, `ConsensusReached`), so a malformed or hallucinated
  payload from an agent is rejected at the boundary instead of corrupting
  history. `ArtifactDrafted` is shared by both review phases (see the
  `review` command bullet below) rather than being spec-specific.
- **Human-in-the-loop escalation**: on deadlock the framework surfaces the
  opposing positions and the pane to attach to, then blocks in place awaiting
  confirmation — a human can break the tie in the agent's own terminal and
  resume the same run with a new round, rather than the process exiting and
  requiring a separate resume command.
- **`roundtable review` CLI command** that starts a review round against
  either the `spec` target (the OpenSpec change) or the `code` target (its
  implementation). A spec review needs a user-supplied description of what
  to build, since there is no prior artifact to draft from; a code review
  instead drafts from the spec phase's consensus-approved state and refuses
  to start until that consensus is recorded. The two targets are separate,
  independently resumable invocations — reaching spec consensus stops the
  run without starting code review, which a user can pick up later. `review`
  exits `0` on consensus, `1` on an orchestration failure (a missing
  prerequisite, a herdr error, an invalid roster), and `2` when a run ends in
  a deadlock the human declined to continue past — a caller can distinguish
  "review disagreed" from "review broke" by exit code alone.
- **Dependencies added**: `pydantic`, `typer` (CLI), and `pydantic-settings`
  for config loading. Runtime dependency on the `herdr` binary and `git`.

Agents exchange structured results by writing JSON files to a per-round drop
directory, which the framework validates and then records. Terminal output is
used only for liveness and state, never parsed as data — scraping a TUI for
structured payloads is too brittle to build a state machine on.

## Capabilities

### New Capabilities
- `project-scaffolding`: the `init` command — workspace layout, Git
  initialization, event store creation, and agent roster configuration,
  including how it behaves against an already-initialized directory.
- `agent-orchestration`: the herdr control surface — pane creation, agent
  startup, prompt submission, state waiting, output reading, teardown, and
  the failure modes each can return.
- `spec-review-rounds`: the draft → critique → revise → consensus lifecycle,
  including severity-gated consensus, the round limit, deadlock declaration,
  and human escalation.
- `event-store`: the append-only event log — event schemas and shared
  envelope, validation-at-the-boundary guarantees, ordering, and replay.
- `review-command`: the `review` CLI command — spec vs. code target
  selection, the spec phase's required build context, the code phase's
  consensus-gated start and approved-spec seeding, and the independent
  resumability of the two phases.

### Modified Capabilities

None. This is the project's first set of specs.

## Impact

- **New source packages** under `src/roundtable/`: `cli`, `herdr` (subprocess
  client), `orchestration`, `events`, `store`, `config`.
- **`src/roundtable/__init__.py`** gains the package's public entry points;
  `pyproject.toml` gains a `[project.scripts]` console entry point for
  `roundtable` plus the new runtime dependencies (currently `dependencies = []`).
- **Tests**: new pytest-bdd features under `tests/bdd/` per capability, with
  the herdr client faked at the subprocess boundary so the suite needs no live
  herdr server. The placeholder feature in `tests/bdd/example/` is superseded
  and removed. Coverage must stay above the 80% floor in `.coveragerc`.
- **External contracts assumed**: herdr `0.9.x` CLI (`pane split`,
  `agent start|prompt|wait|read`, `api snapshot`), which emits JSON on stdout.
  A herdr major-version bump is the main upgrade risk and is isolated behind
  the `herdr` client module.
- **Not in scope**: remote/multi-machine orchestration and publishing the
  package to PyPI. Agent kind is user-selectable at `init` (e.g. `claude`,
  `codex`) and passed through to herdr's `--kind` flag as-is; roundtable does
  not validate that a chosen kind is installed or behaves like `claude` —
  that responsibility stays with herdr. Automatically starting code review
  the moment spec consensus is reached is also out of scope — the two phases
  are deliberately separate invocations.
