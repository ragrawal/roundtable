# Spec Delta

## Purpose

Gives an operator watching a review run a step-by-step narration of what is
happening while it runs, instead of silence until the single final outcome
line, so a run that takes over a minute of real agent turns doesn't look
stalled or hung.

## ADDED Requirements

### Requirement: Round start is reported

The framework SHALL report the start of each round, identified by its round
number, before prompting any agent for that round.

#### Scenario: First round is announced
- **WHEN** a review run begins its first round
- **THEN** a status update naming round 1 is reported before the developer
  agent is prompted for a draft

#### Scenario: A revision round is announced
- **WHEN** a revision round starts following a prior round's outcome
- **THEN** a status update naming the new round number is reported before
  the developer agent is prompted to revise

### Requirement: Turn-level activity is reported

The framework SHALL report when the developer agent begins drafting or
revising, and when the reviewer agents begin critiquing a draft, before
submitting the corresponding prompt.

#### Scenario: Drafting is announced
- **WHEN** the developer agent is about to be prompted for the first draft
- **THEN** a status update reports that the developer is drafting, before
  the prompt is submitted

#### Scenario: Revising is announced
- **WHEN** the developer agent is about to be prompted to revise
- **THEN** a status update reports that the developer is revising, before
  the prompt is submitted

#### Scenario: Critique is announced
- **WHEN** the reviewer agents are about to be prompted to critique a draft
- **THEN** a status update reports that the reviewers are critiquing the
  draft, before any reviewer is prompted

### Requirement: Each reviewer's result is reported as it arrives

As each reviewer's turn completes, the framework SHALL report a summary of
that reviewer's result — the reviewer's name and the number of findings it
raised, grouped by severity — without waiting for every reviewer in the
round to finish.

#### Scenario: A reviewer's result is reported on completion
- **WHEN** one reviewer's critique turn completes while another reviewer in
  the same round is still working
- **THEN** a status update summarizing the finished reviewer's findings is
  reported immediately, before the other reviewer's turn completes

#### Scenario: A reviewer with no findings is reported
- **WHEN** a reviewer completes a critique turn with an empty findings list
- **THEN** a status update reports that the reviewer raised no findings

### Requirement: Round outcome is reported

When a round concludes, the framework SHALL report its outcome — consensus
reached, revision requested, or deadlock declared — with enough detail to
distinguish which occurred.

#### Scenario: Consensus outcome is reported
- **WHEN** a round ends in consensus
- **THEN** a status update reports that consensus was reached, naming the
  approving reviewers

#### Scenario: Revision outcome is reported
- **WHEN** a round ends with a revision requested
- **THEN** a status update reports that a revision was requested, naming the
  number of outstanding critiques driving it

#### Scenario: Deadlock outcome is reported
- **WHEN** a round ends in a declared deadlock
- **THEN** a status update reports the deadlock and the contested section
