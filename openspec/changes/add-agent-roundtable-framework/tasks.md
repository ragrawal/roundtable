# Tasks

## 1. Package setup

- [ ] 1.1 Add runtime dependencies `pydantic`, `pydantic-settings`, and `typer` to `pyproject.toml` (replacing `dependencies = []`) and verify `uv sync` succeeds and `uv run python -c "import pydantic, typer"` exits 0
- [ ] 1.2 Add the `roundtable` console entry point under `[project.scripts]` pointing at the CLI app, and verify `uv run roundtable --help` prints usage and exits 0
- [ ] 1.3 Create the package module skeleton (`config`, `events`, `store`, `herdr`, `orchestration`, `cli`) under `src/roundtable/` with docstrings, and verify `uv run poe lint` and `uv run poe typecheck` both pass on the empty modules

## 2. Event models (spec: event-store)

- [ ] 2.1 Implement the shared event envelope model (event id, timestamp, specification id, event type, emitter) with `Field(..., description=...)` on every field and `extra="forbid"`, and verify unit tests show a missing envelope field is rejected naming that field
- [ ] 2.2 Implement the `Severity` string enum (`blocking`, `major`, `minor`, `info`) and verify a parametrized test shows an out-of-set severity is rejected listing the permitted values
- [ ] 2.3 Implement the five payload models (`ArtifactDrafted`, `CritiqueSubmitted`, `RevisionRequested`, `ConsensusDeadlocked`, `ConsensusReached`) with their spec'd required fields — `ArtifactDrafted`'s `content` documented as a reviewer-facing summary rather than the authoritative multi-file state, which its version identifier references — and verify a parametrized test covers one valid and one missing-required-field case per type
- [ ] 2.4 Combine the payload models into a `RoundtableEvent` discriminated union on the event-type field, and verify tests show an unrecognized event type is rejected naming the type and an undefined extra field is rejected naming the field

## 3. Event store (spec: event-store)

- [ ] 3.1 Implement the append-only JSONL store with open/append/replay operations keyed by specification id, exposing no mutation or delete operation, and verify a test asserts read order equals append order for four events
- [ ] 3.2 Enforce event-id uniqueness via the set of ids loaded at open time, and verify a test shows appending a duplicate id is rejected and leaves the stored events unchanged
- [ ] 3.3 Validate every event fully before writing any bytes, and verify a test shows an invalid event submitted to a three-event store leaves it byte-for-byte unchanged with no field defaulted
- [ ] 3.4 Implement per-specification replay isolation and empty-replay behavior, and verify tests show replaying one of two specifications returns only its events in order, and replaying an unknown specification id returns an empty sequence rather than raising
- [ ] 3.5 Verify restart durability with a test that appends events, closes the store, reopens it from disk, and asserts the same events in the same order
- [ ] 3.6 Add thread-safety guarantees to `EventStore.append` using `threading.Lock`, so it supports concurrent critique emission without line corruption, and verify a test appends events from multiple threads concurrently and asserts every line is complete and valid with no interleaving

## 4. Workspace configuration (spec: project-scaffolding)

- [ ] 4.1 Implement the `AgentRoster` and agent-profile models (name, role, persona, agent kind) with roster validation pushed onto the model — exactly one developer, at least one reviewer, unique names — and verify parametrized tests cover each violation reporting which constraint failed
- [ ] 4.2 Implement `roundtable.toml` loading via `pydantic-settings`, including the configurable round limit with a default of 3 and a minimum of 1, and verify tests cover a valid file, a round limit below the minimum, and a malformed file

## 5. herdr client (spec: agent-orchestration)

- [ ] 5.1 Implement the `HerdrClient` subprocess seam that invokes the `herdr` CLI and parses the `{"id", "result"}` JSON envelope from stdout, and verify tests against recorded herdr `0.9.1` output fixtures parse `api snapshot` and `agent list` correctly
- [ ] 5.2 Implement herdr version detection and the supported-major-version assertion, and verify tests cover a supported version passing and an unsupported version raising an error that names both the detected version and the supported range
- [ ] 5.3 Implement typed errors for herdr's named failure modes (`agent_blocked`, `agent_prompt_stalled`, `timeout`, missing binary) instead of a raw subprocess error, and verify a parametrized test maps each herdr failure output to its typed error
- [ ] 5.4 Implement `pane split` / `pane close` wrappers returning and accepting pane ids, and verify tests assert the composed argument lists including `--cwd` and direction
- [ ] 5.5 Implement `agent start` (into an existing pane id, with startup timeout), `agent prompt` (with `--wait`/`--until`/`--timeout`), `agent wait`, and `agent read` wrappers, and verify tests assert the composed argument lists and that `agent start` is never called without a pane id
- [ ] 5.6 Enforce a hard subprocess-level timeout (not just a `--timeout` flag passed through) on every `agent prompt --wait` call, and verify `HerdrClient` is safe to invoke from multiple threads concurrently with a test that runs several calls in parallel against a fake subprocess layer and asserts none blocks another

## 6. Review round decision logic (spec: spec-review-rounds)

- [ ] 6.1 Implement the pure `ReviewRound` decision model mapping (draft version, collected critiques, round number, round limit) to `ReachedConsensus | RequestRevision | Deadlocked`, and verify a table-driven parametrized test with `pytest.param(..., id=...)` covers consensus with no findings, consensus with only `major` findings, revision on a single `blocking` critique, and deadlock at the round limit
- [ ] 6.2 Carry non-blocking findings into the consensus result as advisory and record approving reviewers plus the final state identifier, and verify a test asserts a `major` finding appears in the consensus result and does not prevent consensus
- [ ] 6.3 Build the deadlock result to name the contested section, each opposing position with the agent holding it, and the trade-offs, and verify a test asserts all three are present for a two-reviewer disagreement
- [ ] 6.4 Treat an incomplete round (a reviewer turn that failed or timed out) as not eligible for consensus, and verify a test shows a round with one failed reviewer reports incompleteness naming that reviewer instead of declaring consensus

## 7. Review runner (specs: agent-orchestration, spec-review-rounds)

- [ ] 7.1 Implement pane allocation and agent startup for the full roster with recorded agent-name-to-pane-id mapping, and verify tests with a fake herdr client assert three agents get three panes and that a mid-roster allocation failure tears down already-allocated panes
- [ ] 7.2 Implement the per-round result-artifact protocol under the gitignored `.roundtable/scratch/<round>/` directory — per-round directory, prompt-specified result path, read-and-validate after the terminal state, artifacts left on disk rather than deleted after the round — and verify tests cover a well-formed result being read, a missing result producing a named failure that includes a terminal snapshot as diagnostic context, and the scratch directory still containing that round's files once the round has ended
- [ ] 7.3 Implement the drafting phase including the Git commit of the accepted draft and the `ArtifactDrafted` event, and verify tests in a temporary Git repository assert the commit exists and the recorded event references it, and that a failed draft starts no critique phase
- [ ] 7.4 Implement the parallel critique phase over a `ThreadPoolExecutor` with per-reviewer prompt isolation, and verify tests assert no reviewer's prompt contains another reviewer's critique text from the same round and that one `CritiqueSubmitted` event is recorded per critique
- [ ] 7.5 Implement the revision loop — `RevisionRequested` carrying the blocking critiques, developer revision prompt, new committed draft version, next round — and verify tests assert the revision request contains all blocking critiques and the developer prompt includes them
- [ ] 7.6 Implement run termination recording `ConsensusReached` or `ConsensusDeadlocked`, and verify tests assert the correct terminal event for a consensus run and a round-limit-exhausted run
- [ ] 7.7 Implement teardown that closes only framework-allocated panes, retains contested panes on deadlock, and collects rather than raises close failures in a `finally`, and verify tests assert panes not created by the framework are never closed and that a close failure surfaces as a secondary warning without masking the original failure
- [ ] 7.8 Implement human-escalation reporting on deadlock (pane id and attach instruction per contested agent, no auto-resolution), and verify a test asserts both are reported and that no position is selected
- [ ] 7.9 Implement the deadlock attachment continuation contract: after reporting escalation instructions, block on a confirmation prompt rather than returning control to the caller; on confirmation start a new critique round against the current committed draft without re-running the draft phase, exempt from the configured round limit; on explicit decline end the run recording the deadlock, and verify tests cover both the confirm-and-resume path and the decline-and-exit path, asserting the resumed round's number is not compared against the round limit

## 8. CLI (spec: project-scaffolding)

- [ ] 8.1 Implement prerequisite validation for `git` and a supported `herdr` that runs before any filesystem write, and verify tests assert a missing `herdr` and an unsupported `herdr` version each exit non-zero with the required message and leave the target directory unchanged
- [ ] 8.2 Implement `roundtable init`'s interactive prompt sequence — agent count, then per-agent name/role/focus-prompt/kind, then the round limit — where role and kind are each offered as a `click.Choice`-style prepopulated list with a custom-entry fallback (role from developer/product manager/senior engineer/security reviewer/QA engineer, kind from claude/codex), and verify a `CliRunner`-scripted test asserts the written `roundtable.toml` matches the scripted answers
- [ ] 8.3 Implement the `ROLE_FOCUS_PROMPTS` mapping from each predefined role to its default focus prompt, wire it as the focus-prompt question's default when the role matched the mapping, and require the focus prompt to be entered with no default when the role is custom, and verify tests cover accepting a predefined role's default focus prompt, overriding it, and being required to author one for a custom role
- [ ] 8.4 Wire `init` to create the OpenSpec layout, Git repository with initial commit, empty event store, a gitignored `.roundtable/scratch/` directory, and the roster/round-limit from 8.2 (defaulting to one developer, a product-management reviewer, a security reviewer, `claude` kind throughout, and a round limit of 3 when every prompt's default is accepted), and verify tests assert all five exist and the reported path and roster
- [ ] 8.5 Implement `init` against an existing Git repository by reusing it, and verify a test asserts existing history and working tree are unmodified while the remaining components are created
- [ ] 8.6 Implement `init` conflict refusal and the explicit reinitialize flag, and verify tests assert refusal exits non-zero naming the conflicting path with no changes, and that reinitialize replaces the roster while preserving the event store and Git history
- [ ] 8.7 Implement pre-population of 8.2's and 8.3's prompt defaults from an existing `roundtable.toml` (agent count, each agent's name/role/focus prompt/kind, round limit), and verify a `CliRunner`-scripted test that accepts every default against an existing three-agent config asserts the resulting roster and round limit are unchanged
- [ ] 8.8 Implement the `review` command's shared shell wiring config, store, herdr client, and runner together with exit codes 0 for consensus, 2 for deadlock, and 1 for orchestration failure, and verify tests assert each exit code and that a roster with no reviewers or duplicate names fails before any agent is started
- [ ] 8.9 Implement `init`'s `--config <path>` flag that loads a `roundtable.toml`-shaped file and skips every interactive prompt, validating the loaded roster the same way an interactively built one is validated, and verify tests assert a valid config file produces the same workspace an equivalent interactive session would, and an invalid one (e.g. no developer) is rejected before any filesystem write

## 9. Review command (spec: review-command)

- [ ] 9.1 Implement `review`'s target dispatch (`spec` | `code`) and specification-identifier argument on top of 8.8's shell, driving the same runner from section 7 against a different artifact source per target, and verify a test asserts each target reaches the runner with the correct artifact source
- [ ] 9.2 Implement the required build-context input for `review spec` (inline description or a context-file reference) and its inclusion in the developer agent's first drafting prompt, and verify tests cover an inline description, a context file, and refusal with neither, the refusal exiting non-zero with no agent turn started
- [ ] 9.3 Implement compound specification identifiers keying the spec phase under `<id>` and the code phase under a derived id such as `<id>:code`, so their event histories and Git state replay independently, and verify a test asserts replaying the spec-phase id after a code-phase run still returns only spec-phase events
- [ ] 9.4 Implement `review code`'s context resolution — replaying the spec-phase id for its latest `ConsensusReached` event, then passing its recorded Git commit SHA and content directly into the developer agent's first drafting prompt rather than re-deriving them some other way — and verify a test asserts the code-phase prompt includes that exact commit SHA and content with no separate description required
- [ ] 9.5 Implement the prior-spec-consensus gate for `review code`, and verify a test asserts a code review attempted before spec consensus (no consensus event, or the spec phase incomplete/revising/deadlocked) exits non-zero reporting the gate and starts no agent turn

## 10. Integration and cleanup

- [ ] 10.1 Add pytest-bdd feature files per capability, including `review-command`, under `tests/bdd/<capability>/` with step definitions in `tests/bdd/actions/` re-exported through `tests/bdd/conftest.py`, following the `write-bdd-tests` skill, and verify `uv run poe test --full` collects and passes them
- [ ] 10.2 Add end-to-end BDD scenarios: a two-round run to consensus, a run to deadlock, and a spec-consensus-then-later-code-review run started as two separate invocations, all against a fake herdr client with no live herdr server, and verify each passes and that the event log replays the full round sequence for its own phase
- [ ] 10.3 Remove the superseded placeholder feature in `tests/bdd/example/` and verify `uv run poe test --full` still passes with coverage above the `.coveragerc` threshold
- [ ] 10.4 Update `README.md` with installation, `roundtable init`, and `roundtable review spec|code` usage including the exit-code and context-requirement contracts, and verify the documented commands run as written against a scratch directory
- [ ] 10.5 Run the full quality gate and verify `uv run poe check --full` passes end to end
