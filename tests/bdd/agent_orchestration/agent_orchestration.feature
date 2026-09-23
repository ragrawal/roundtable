Feature: Agent orchestration
  Runs each agent in its own isolated terminal pane and drives it through a
  turn, so orchestration failures surface as named, actionable errors rather
  than a hang.

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

  Scenario: A reviewer turn failing makes the round incomplete
    Given a roster of one developer and two reviewers
    And the "sec" reviewer never writes a critique result
    When a review run starts with build context "a widget"
    Then the run reports the round as incomplete, naming "sec"

  Scenario: Teardown after consensus releases every pane
    Given a roster of one developer and two reviewers
    When a review run starts with build context "a widget"
    Then the "dev" agent's pane is released
    And the "sec" agent's pane is released
    And the "pm" agent's pane is released

  Scenario: Teardown after deadlock leaves the contested pane open
    Given a roster of one developer and two reviewers
    And the "sec" reviewer blocks on "Auth"
    When a review run starts with build context "a widget"
    Then the run declares a deadlock on "Auth"
    And the "sec" agent's pane remains open for escalation
    And the "dev" agent's pane is released
    And the "pm" agent's pane is released

  Scenario: Round scratch artifacts persist after the round for diagnosis
    Given a roster of one developer and two reviewers
    When a review run starts with build context "a widget"
    Then round 1's scratch artifacts remain on disk
