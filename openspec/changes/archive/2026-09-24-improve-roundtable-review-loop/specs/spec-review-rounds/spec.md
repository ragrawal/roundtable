# Spec Delta

## MODIFIED Requirements

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
