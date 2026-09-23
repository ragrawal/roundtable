Feature: Event store
  Records every state change in a review run as a validated, append-only
  event log, so a run's history is auditable and rejected payloads never
  become corrupt history.

  Scenario: Events are replayed in append order
    Given an empty event store
    When 3 drafts are appended for "widget"
    Then replaying "widget" returns 3 events in order

  Scenario: A malformed event is rejected before it reaches the store
    Given an empty event store
    When a critique with severity "critical" is submitted for "widget"
    Then the submission is rejected naming the "severity" field
    And replaying "widget" returns 0 events in order

  Scenario: A duplicate event id is rejected and the store is left unchanged
    Given an empty event store
    When 1 drafts are appended for "widget"
    And the first appended event is appended again
    Then the submission is rejected as a duplicate
    And replaying "widget" returns 1 events in order

  Scenario: Replay excludes other specifications' events
    Given an empty event store
    When 2 drafts are appended for "widget"
    And 3 drafts are appended for "gadget"
    Then replaying "widget" returns 2 events in order
    And replaying "gadget" returns 3 events in order

  Scenario: Events survive the store being reopened
    Given an empty event store
    When 2 drafts are appended for "widget"
    And the store is reopened
    Then replaying "widget" returns 2 events in order
