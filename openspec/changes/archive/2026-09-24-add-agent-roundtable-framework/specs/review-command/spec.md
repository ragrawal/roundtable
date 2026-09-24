# Spec Delta

## Purpose

Defines the `review` command that starts a spec-review-rounds run against
either an OpenSpec change or the code that implements it, so a user can
complete spec review, stop, and pick code review back up in a later,
separate invocation once the spec is approved.

## ADDED Requirements

### Requirement: Review target selection

The `review` command SHALL accept the identifier of the specification under
review and a target of either `spec` or `code`, and SHALL drive the
spec-review-rounds lifecycle (draft, critique, revise, consensus or
deadlock) against that target's artifact: the OpenSpec change for `spec`,
the implementation for `code`.

#### Scenario: Running a spec review
- **WHEN** a user runs `review` with target `spec` for a specification with
  no prior spec-phase history
- **THEN** the command starts a spec-review-rounds run whose developer turns
  draft and revise the OpenSpec change

#### Scenario: Running a code review
- **WHEN** a user runs `review` with target `code` for a specification whose
  spec phase has reached consensus
- **THEN** the command starts a spec-review-rounds run whose developer turns
  draft and revise the implementation

### Requirement: Spec drafting requires user-supplied context

There is no prior artifact for a spec-phase run to draft from. `roundtable
review spec` SHALL require the user to supply a description of what is to be
built, either inline or as a reference to a context file, and SHALL include
that description in the developer agent's first drafting prompt. The command
SHALL refuse to start a spec review with no context supplied.

#### Scenario: Spec review with an inline description
- **WHEN** a user runs `review spec` with an inline description of the
  feature to build
- **THEN** the description is included in the developer agent's first
  drafting prompt

#### Scenario: Spec review with a context file
- **WHEN** a user runs `review spec` with a reference to a context file
  instead of an inline description
- **THEN** the file's content is included in the developer agent's first
  drafting prompt

#### Scenario: Spec review refuses to start without context
- **WHEN** a user runs `review spec` with neither an inline description nor
  a context file
- **THEN** the command exits non-zero reporting that a description of what
  to build is required
- **AND** no developer agent turn is started

### Requirement: Code review is seeded by the approved spec

`roundtable review code` SHALL use the specification's consensus-approved
state — the Git state identifier and content recorded on its spec-phase
`ConsensusReached` event — as the developer agent's implementation context,
and SHALL NOT require the user to supply a separate description.

#### Scenario: Code review starts from the approved spec
- **WHEN** a user runs `review code` for a specification whose spec phase
  reached consensus at a given Git state
- **THEN** the developer agent's first drafting prompt for the code phase
  includes that approved state's content
- **AND** the command does not prompt for or require a separate description

### Requirement: Code review requires prior spec consensus

`roundtable review code` SHALL refuse to start for a specification whose
spec phase has not reached consensus, reporting that spec review must
complete first.

#### Scenario: Code review attempted before spec consensus
- **WHEN** a user runs `review code` for a specification whose spec phase is
  incomplete, in a revision round, or deadlocked
- **THEN** the command exits non-zero reporting that spec review has not
  reached consensus
- **AND** no developer agent turn is started

### Requirement: Spec and code review are independently resumable

A spec review and a code review for the same specification SHALL be separate
invocations of the `review` command. Reaching spec consensus SHALL end the
run without starting or implying a code review. A code review MAY be
started in a later, separate invocation once spec consensus is recorded.

#### Scenario: Stopping after spec consensus
- **WHEN** a spec-phase run reaches consensus
- **THEN** the command exits reporting the spec consensus, and no code-phase
  agent is started

#### Scenario: Starting code review later
- **WHEN** a user runs `review code` in a new invocation for a specification
  whose spec-phase consensus was recorded in an earlier, separate invocation
- **THEN** the code-phase run starts using that recorded consensus as its
  context
