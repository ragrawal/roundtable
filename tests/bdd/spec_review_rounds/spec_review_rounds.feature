Feature: Spec review rounds
  A review round reaches consensus when no reviewer raises a blocking
  critique, requests a revision when one does and rounds remain, declares a
  deadlock when the round limit is reached with blocking critiques
  outstanding, and can be resumed by a human's confirmation without
  re-drafting.

  Scenario: No findings reach consensus
    Given a draft awaiting critique
    And "security" approves with no findings
    And "qa" approves with no findings
    When the round is decided as round 1 of 3
    Then consensus is declared

  Scenario: Only major findings reach consensus, recorded as advisory
    Given a draft awaiting critique
    And "security" raises a "major" critique on "Auth"
    And "qa" approves with no findings
    When the round is decided as round 1 of 3
    Then consensus is declared
    And the advisory findings include a "major" finding on "Auth"

  Scenario: A single blocking critique requests a revision
    Given a draft awaiting critique
    And "security" raises a "blocking" critique on "Auth"
    And "qa" approves with no findings
    When the round is decided as round 1 of 3
    Then a revision round is requested
    And the requested revision carries 1 critique(s)

  Scenario: Blocking critiques from multiple reviewers are all carried into the revision
    Given a draft awaiting critique
    And "security" raises a "blocking" critique on "Auth"
    And "qa" raises a "blocking" critique on "Payments"
    When the round is decided as round 1 of 3
    Then a revision round is requested
    And the requested revision carries 2 critique(s)

  Scenario: Blocking critiques outstanding at the round limit declare a deadlock
    Given a draft awaiting critique
    And "security" raises a "blocking" critique on "Auth"
    And "qa" approves with no findings
    When the round is decided as round 3 of 3
    Then a deadlock is declared

  Scenario: A reviewer's turn failing makes the round incomplete
    Given a draft awaiting critique
    And "security" raises a "blocking" critique on "Auth"
    And "qa"'s turn times out
    When the round is decided as round 1 of 3
    Then the round is reported as incomplete

  Scenario: A human confirming resolution after a deadlock resumes without re-drafting
    Given a review that deadlocks once and then resolves on the human's confirmation
    When the run proceeds, confirming resolution after the deadlock
    Then the resumed run reaches consensus
    And the human was asked to confirm exactly once
    And the developer is not prompted to draft again after the deadlock

  Scenario: Declining to continue after a deadlock ends the run
    Given a review that deadlocks once and then resolves on the human's confirmation
    And the human will decline to continue
    When the run proceeds, confirming resolution after the deadlock
    Then the run ends in the declared deadlock
    And the human was asked to confirm exactly once
