# spec-review-rounds

## Purpose

Defines the draft, critique, and revision lifecycle that carries a reviewed
artifact — an OpenSpec change in the spec phase, or its implementation in the
code phase, as selected by the `review-command` capability — from a first
draft to either an agreed state or an explicitly declared deadlock, so a
review always terminates with a recorded, reviewable outcome instead of
looping indefinitely.

## Requirements

### Requirement: Draft phase

A review run SHALL begin by directing the developer agent to produce a draft
of the specification under review. The framework SHALL commit the accepted
draft to the workspace Git repository and record a draft event carrying the
draft's version identifier and content. A run SHALL NOT proceed to critique
until a draft has been committed.

#### Scenario: Developer produces the first draft
- **WHEN** a review run starts for a specification that has no draft yet
- **THEN** the developer agent is prompted to draft it, the resulting draft is
  committed to Git, and a draft event is recorded referencing that commit

#### Scenario: Developer fails to produce a draft
- **WHEN** the developer agent's drafting turn ends without a usable draft
- **THEN** the run fails reporting that drafting did not produce a draft
- **AND** no critique phase is started

### Requirement: Parallel critique phase

For each round, the framework SHALL prompt every reviewer agent with the
current committed draft and collect one critique set per reviewer. Reviewer
turns SHALL be independent: no reviewer's prompt SHALL include another
reviewer's critiques from the same round. Each critique SHALL identify the
section it targets, a severity, a description of the issue, and MAY include a
suggested patch. The framework SHALL record one critique event per critique.

#### Scenario: All reviewers critique a draft
- **WHEN** a round begins with a committed draft and two reviewer agents
- **THEN** both reviewers are prompted with the same draft, and every critique
  each returns is recorded as a critique event referencing that draft version

#### Scenario: A reviewer approves without findings
- **WHEN** a reviewer returns an empty critique set for a draft
- **THEN** the round records that reviewer as having raised no blocking
  concerns for that draft version

#### Scenario: A reviewer turn fails
- **WHEN** one reviewer's turn times out while the other completes
- **THEN** the round is reported as incomplete, naming the reviewer that
  failed, and consensus is not declared for that draft version

### Requirement: Consensus is gated on blocking critiques

Critique severity SHALL be one of `blocking`, `major`, `minor`, or `info`.
Consensus SHALL be reached for a draft version when every reviewer has
completed its turn for that version and no reviewer raised a `blocking`,
`major`, or `minor` critique. Only `info` critiques SHALL NOT prevent
consensus, and SHALL be carried into the consensus record as advisory
findings. On consensus the framework SHALL record a consensus event carrying
the approving reviewers and the final committed state identifier.

#### Scenario: Only info-level critiques
- **WHEN** every reviewer completes its turn for a draft version and the
  highest severity raised is `info`
- **THEN** consensus is declared for that version, and the `info` findings
  are recorded in the consensus record as advisory

#### Scenario: One blocking critique
- **WHEN** one reviewer raises a `blocking` critique and the other raises none
- **THEN** consensus is not declared, and a revision round is requested

#### Scenario: One major critique
- **WHEN** one reviewer raises a `major` critique and no reviewer raises a
  `blocking` critique
- **THEN** consensus is not declared, and a revision round is requested

#### Scenario: One minor critique
- **WHEN** one reviewer raises a single `minor` critique and no reviewer
  raises anything more severe
- **THEN** consensus is not declared, and a revision round is requested

#### Scenario: Consensus record identifies the agreed state
- **WHEN** consensus is declared
- **THEN** the consensus event names every reviewer that approved and the Git
  state identifier of the draft they approved

### Requirement: Revision rounds are bounded

When a round ends with one or more `blocking`, `major`, or `minor` critiques,
the framework SHALL record a revision request carrying those critiques, and
SHALL prompt the developer agent to revise the draft. Each revision SHALL be
committed as a new draft version and SHALL start a new critique round. The
number of rounds in a run SHALL be bounded by a configurable limit of at
least one, defaulting to three.

#### Scenario: Revision resolves the outstanding critiques
- **WHEN** a revision round produces a draft for which no reviewer raises a
  `blocking`, `major`, or `minor` critique
- **THEN** consensus is declared for the revised version

#### Scenario: Revision request carries critiques of mixed severity
- **WHEN** a round ends with one `blocking` critique from one reviewer and
  one `minor` critique from another
- **THEN** the recorded revision request contains both critiques, and the
  developer agent's revision prompt includes both

#### Scenario: Round limit is reached
- **WHEN** the configured round limit is reached and any `blocking`,
  `major`, or `minor` critique remains outstanding
- **THEN** no further revision round is started, and the run proceeds to
  declare a deadlock

### Requirement: Deadlock is declared explicitly

When a run cannot reach consensus within its round limit, the framework SHALL
declare a deadlock rather than silently stopping or accepting the draft. The
deadlock record SHALL name the contested section, the opposing positions, and
the trade-offs between them. Declaring a deadlock SHALL NOT by itself end the
run — see "Human escalation blocks for resolution and resumes without
re-drafting" for what happens next. If the human subsequently declines to
continue past the deadlock, the run SHALL exit with a non-zero status
distinguishable from an orchestration failure.

#### Scenario: Deadlock record content
- **WHEN** a deadlock is declared after the round limit is reached
- **THEN** the recorded deadlock event names the contested section, states
  each opposing position with the agent that holds it, and states the
  trade-offs between them

#### Scenario: Deadlock exit status
- **WHEN** a human declines to continue past a declared deadlock
- **THEN** the run exits non-zero with a status that a caller can distinguish
  from both consensus and an orchestration failure

### Requirement: Human escalation blocks for resolution and resumes without re-drafting

On deadlock the framework SHALL leave the contested agents' panes attachable,
report for each the pane identifier and the attach instruction, and then
SHALL block the run awaiting the human's explicit confirmation — so a human
can intervene in the agent's own terminal and signal when they are done,
rather than the run exiting immediately. The framework SHALL NOT resolve a
deadlock on the human's behalf or alter the recorded positions.

When the human confirms resolution, the framework SHALL start a new critique
round against the current committed draft, using the current state of the
contested agents, without re-running the draft phase or any earlier round.
That round SHALL be evaluated by the same consensus/revision/deadlock
decision logic as any other round, and SHALL NOT count against the
configured round limit — the round limit bounds automatic agent revision,
not a round a human has just deliberately unblocked. When the human instead
explicitly declines to continue, the run ends in the declared deadlock (see
"Deadlock is declared explicitly").

#### Scenario: Escalation instructions are reported, then the run blocks
- **WHEN** a deadlock is declared between two reviewers
- **THEN** the run reports each contested agent's pane identifier and the
  command to attach to it, and then blocks awaiting human confirmation
  instead of exiting

#### Scenario: Confirmed resolution resumes with a new round
- **WHEN** the human confirms resolution following a deadlock
- **THEN** the framework starts a new critique round against the same
  committed draft, without re-running the draft phase or any earlier round

#### Scenario: A resumed round can reach consensus
- **WHEN** the round started after human confirmation ends with no reviewer
  raising a `blocking`, `major`, or `minor` critique
- **THEN** consensus is declared and the run exits 0

#### Scenario: A resumed round does not count against the round limit
- **WHEN** a round started after human confirmation is evaluated
- **THEN** its round number is not compared against the configured round
  limit to decide whether to declare a further deadlock

#### Scenario: Declining to continue ends the run in deadlock
- **WHEN** the human explicitly declines to continue at the confirmation
  prompt
- **THEN** the framework records the deadlock and stops, without choosing
  between the opposing positions, and the run exits non-zero

### Requirement: A run's history is reconstructable

Every run SHALL be reconstructable after the fact from its recorded events and
Git history alone: the sequence of draft versions, the critiques raised
against each, the revisions requested, and the terminating outcome. Each draft
version referenced by an event SHALL correspond to a commit in the workspace
repository.

#### Scenario: Reconstructing a completed run
- **WHEN** a user inspects a workspace after a run that took two rounds and
  ended in consensus
- **THEN** the recorded events yield both draft versions in order, the
  critiques against each, the revision request between them, and the
  consensus outcome

#### Scenario: Every referenced draft version exists in Git
- **WHEN** a run's events are inspected after the run ends
- **THEN** every draft version identifier appearing in an event resolves to a
  commit in the workspace repository
