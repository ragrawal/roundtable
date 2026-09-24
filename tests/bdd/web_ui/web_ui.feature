Feature: Roundtable web UI
  A roster editor and a live event feed served over an existing workspace,
  with no changes to the underlying event store or config contracts.

  Scenario: Full roster edit-and-save round trip
    Given a workspace with a roundtable.toml roster of "dev" and "sec"
    And the web UI app is running for that workspace
    When the operator edits "sec"'s persona to "Focus on auth boundaries." and saves
    Then the save succeeds
    And the roster read back shows "sec" with persona "Focus on auth boundaries."
    And the round_limit is unchanged

  Scenario: A concurrent save is denied and then succeeds after retry
    Given a workspace with a roundtable.toml roster of "dev" and "sec"
    And the web UI app is running for that workspace
    And another session is already holding the roster lock
    When the operator saves a roster edit
    Then the save is denied as locked
    When the other session releases the roster lock
    And the operator saves the same roster edit again
    Then the save succeeds

  Scenario: A live feed reflects events as they are appended to the real store
    Given a workspace with a roundtable.toml roster of "dev" and "sec"
    And the web UI app is running for that workspace
    And an operator is watching the event feed for specification "widget"
    When a draft is appended for specification "widget"
    Then the feed delivers the draft event
    When a critique is appended for specification "widget"
    Then the feed delivers the critique event
    And no event is delivered twice

  Scenario: Status transitions from deadlocked to in progress after a resumed round's critique
    Given a workspace with a roundtable.toml roster of "dev" and "sec"
    And the web UI app is running for that workspace
    And specification "widget" has reached a deadlock
    Then the status for "widget" shows outcome "deadlocked (may still be active)"
    When a critique resuming the round is appended for specification "widget"
    Then the status for "widget" shows outcome "in progress (estimated)"
