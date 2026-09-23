Feature: Review command
  `roundtable review` drives a spec or code review round to completion:
  consensus, deadlock, or an independently resumable code phase seeded by an
  approved spec.

  Scenario: A two-round run reaches consensus
    Given a roundtable workspace with a developer and a security reviewer and a round limit of 2
    And the security reviewer blocks on "Auth" in round 1
    When roundtable review spec "widget" is run with description "a self-sealing stem bolt"
    Then the review reaches consensus
    And the event log for "widget" replays 2 draft(s) ending in consensus

  Scenario: A run ends in a declared deadlock
    Given a roundtable workspace with a developer and a security reviewer and a round limit of 1
    And the security reviewer blocks on "Auth" in round 1
    When roundtable review spec "widget" is run with description "a self-sealing stem bolt"
    Then the review deadlocks on "Auth"
    And the event log for "widget" replays 1 draft(s) ending in deadlock

  Scenario: Spec consensus, then a later independent code review
    Given a roundtable workspace with a developer and a security reviewer and a round limit of 1
    When roundtable review spec "widget" is run with description "a self-sealing stem bolt"
    Then the review reaches consensus
    When roundtable review code "widget" is run
    Then the review reaches consensus
    And the event log for "widget" contains only its own events
    And the event log for "widget:code" contains only its own events
