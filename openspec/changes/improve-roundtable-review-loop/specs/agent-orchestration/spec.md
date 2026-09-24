# Spec Delta

## MODIFIED Requirements

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
