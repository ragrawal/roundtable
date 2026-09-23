Feature: Live herdr integration
  Exercises HerdrClient's pane commands against the real installed herdr
  binary (never against a fake), so wire-format drift between this client
  and herdr's actual CLI is caught here instead of surfacing deep inside a
  live review run. Skipped when no supported herdr install is on PATH.

  Scenario: Splitting and closing a real pane round-trips cleanly
    Given a temporary directory
    And the real herdr binary is available and supported
    When a new pane is split "right" in a temporary directory
    Then a pane id is returned
    And closing that pane succeeds

  Scenario: Closing an unknown pane raises a named herdr error
    Given the real herdr binary is available and supported
    When closing pane "definitely-not-a-real-pane-id" is attempted
    Then a HerdrCommandError is raised
