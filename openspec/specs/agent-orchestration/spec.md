# agent-orchestration

## Purpose

Gives the framework a reliable way to run each agent in its own isolated
terminal and drive it through a turn, so that reviewer critiques are formed
without shared context and every orchestration failure surfaces as a named,
actionable error rather than a hang.

## Requirements

### Requirement: One isolated pane per agent

The framework SHALL allocate a dedicated terminal pane for each agent in the
roster and start that agent in it. Each pane SHALL be the only pane an agent
reads from or writes to for the duration of a run, so no agent observes
another agent's conversation. The framework SHALL record the mapping from
agent name to pane identifier and expose it to the user.

#### Scenario: Panes are allocated for the full roster
- **WHEN** a review run starts with a roster of one developer and two
  reviewers
- **THEN** the framework allocates three panes, starts one agent in each, and
  reports each agent's name alongside its pane identifier

#### Scenario: Reviewer contexts stay separate
- **WHEN** two reviewer agents critique the same draft in the same round
- **THEN** neither reviewer's prompt contains the other reviewer's critique
  text

#### Scenario: Pane allocation fails partway through
- **WHEN** allocating a pane for the third agent fails
- **THEN** the run fails reporting which agent could not be placed
- **AND** the panes already allocated for the run are torn down

### Requirement: Agent startup readiness

The framework SHALL confirm that an agent is started and ready for input
before submitting any prompt to it. Startup SHALL be bounded by a timeout.
When an agent does not become ready within the timeout, the framework SHALL
fail reporting the agent name and the timeout, and SHALL NOT submit a prompt
to that agent.

#### Scenario: Agent becomes ready
- **WHEN** the framework starts an agent in an allocated pane and the agent
  reaches a ready state within the startup timeout
- **THEN** the framework proceeds to submit prompts to that agent

#### Scenario: Agent never becomes ready
- **WHEN** an agent does not reach a ready state within the startup timeout
- **THEN** the run fails reporting the agent name and the elapsed timeout
- **AND** no prompt is submitted to that agent

### Requirement: Prompted turns are awaited to a terminal state

The framework SHALL submit a prompt to an agent and wait until that agent
reports a terminal state for the turn — completed, idle, or blocked — or until
a caller-supplied timeout expires. The framework SHALL NOT poll agent output
to infer completion; it SHALL rely on the orchestrator's reported agent state.

#### Scenario: Turn completes
- **WHEN** the framework prompts an agent and the agent reaches a completed or
  idle state before the timeout
- **THEN** the framework treats the turn as finished and proceeds to collect
  that agent's result

#### Scenario: Turn exceeds its timeout
- **WHEN** an agent has not reached a terminal state before the turn timeout
  expires
- **THEN** the framework reports a timeout naming the agent and the elapsed
  duration, and treats the turn as unfinished

#### Scenario: Prompting an already-blocked agent
- **WHEN** the framework attempts to prompt an agent that is already in a
  blocked state
- **THEN** the submission is reported as rejected for that agent, and the
  framework does not record a result for the turn

### Requirement: Results are read as structured artifacts, not terminal text

The framework SHALL collect each agent's turn result by reading a structured
artifact the agent writes to a per-round location, and SHALL treat terminal
output solely as diagnostic context for the human. The framework SHALL NOT
parse an agent's terminal output to obtain event payloads.

#### Scenario: Agent writes a well-formed result
- **WHEN** an agent finishes a turn having written a structured result
  artifact for that round
- **THEN** the framework reads that artifact as the turn's result

#### Scenario: Agent finishes without writing a result
- **WHEN** an agent reaches a completed state but no result artifact exists
  for its turn
- **THEN** the framework reports a missing-result failure naming the agent and
  the expected location
- **AND** captures a snapshot of that agent's recent terminal output as
  diagnostic context in the failure report

### Requirement: Round scratch artifacts are ephemeral

Per-round result artifacts and diagnostic terminal snapshots SHALL be written
under a workspace-local scratch directory that the workspace's `.gitignore`
excludes from version control. They SHALL be retained on disk after a round
completes, for post-mortem diagnosis, rather than deleted — the durable
record of a run is the event store and the Git commits of accepted drafts,
not the scratch directory.

#### Scenario: Round artifacts are gitignored
- **WHEN** a round writes a result artifact or a diagnostic terminal snapshot
- **THEN** it is written under the workspace's scratch directory, which the
  workspace's `.gitignore` excludes from version control

#### Scenario: Scratch artifacts persist after the round for diagnosis
- **WHEN** a round completes, successfully or not
- **THEN** its scratch artifacts remain on disk rather than being deleted,
  available for post-mortem inspection

### Requirement: Run teardown

Once a run has started at least one agent turn in a pane, the framework
SHALL NOT automatically close that pane for any reason — not on consensus,
not on a declared deadlock, and not on an incomplete round. Every pane the
framework allocated and used for a turn SHALL remain open and attachable
after the run ends, regardless of outcome, so the operator can continue
inspecting or interacting with any agent once the run is done. This
requirement does not apply to panes abandoned mid-allocation before any
agent has completed a turn — see "One isolated pane per agent" for that
failure path.

#### Scenario: Panes remain open after consensus
- **WHEN** a run ends in consensus
- **THEN** every pane the framework allocated for the run remains open and
  attachable

#### Scenario: Panes remain open after deadlock
- **WHEN** a run ends in a declared deadlock
- **THEN** every pane the framework allocated for the run remains open and
  attachable, not only the panes of the contested agents

#### Scenario: Panes remain open after an incomplete round
- **WHEN** a round is reported incomplete because a reviewer turn failed or
  timed out
- **THEN** every pane the framework allocated for the run remains open and
  attachable, including the failed reviewer's pane
