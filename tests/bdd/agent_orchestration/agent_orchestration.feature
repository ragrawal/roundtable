Feature: Agent orchestration
  Runs each agent in its own isolated terminal pane and drives it through a
  turn, so orchestration failures surface as named, actionable errors rather
  than a hang. Once a turn has started in a pane, the framework never
  automatically closes it again, for any run outcome.

  Scenario: Panes are allocated for the full roster
    Given a roster of one developer and two reviewers
    When a review run starts with build context "a widget"
    Then three panes are allocated, one per agent

  Scenario: Pane allocation fails partway through
    Given a roster of one developer and two reviewers
    And the "pm" agent's pane cannot be allocated
    When a review run starts with build context "a widget"
    Then the run fails reporting that the "pm" agent could not be placed
    And the panes already allocated for the run are torn down

  Scenario: A reviewer turn failing leaves every allocated pane open
    Given a roster of one developer and two reviewers
    And the "sec" reviewer never writes a critique result
    When a review run starts with build context "a widget"
    Then the run reports the round as incomplete, naming "sec"
    And the "sec" agent's pane remains open for escalation
    And the "dev" agent's pane remains open for escalation
    And the "pm" agent's pane remains open for escalation

  Scenario: Panes remain open after consensus
    Given a roster of one developer and two reviewers
    When a review run starts with build context "a widget"
    Then the "dev" agent's pane remains open for escalation
    And the "sec" agent's pane remains open for escalation
    And the "pm" agent's pane remains open for escalation

  Scenario: Panes remain open after deadlock, not only the contested ones
    Given a roster of one developer and two reviewers
    And the "sec" reviewer blocks on "Auth"
    When a review run starts with build context "a widget"
    Then the run declares a deadlock on "Auth"
    And the "sec" agent's pane remains open for escalation
    And the "dev" agent's pane remains open for escalation
    And the "pm" agent's pane remains open for escalation

  Scenario: Round scratch artifacts persist after the round for diagnosis
    Given a roster of one developer and two reviewers
    When a review run starts with build context "a widget"
    Then round 1's scratch artifacts remain on disk

  Scenario: A reviewer that finishes first is reported before a slower reviewer
    Given a roster of one developer and two reviewers
    And the "pm" reviewer waits for the "sec" reviewer to finish first
    When a review run starts with build context "a widget"
    Then the "sec" reviewer's result is reported before the "pm" reviewer's result
