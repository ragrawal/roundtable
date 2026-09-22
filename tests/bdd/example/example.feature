Feature: Example BDD scenario
  Demonstrates the reusable Given/When/Then steps available in
  tests/bdd/actions/. Replace or extend this feature as the project grows.

  Scenario: The package is importable and reports a version
    Given a temporary directory
    When the user runs "python -c 'import roundtable; print(roundtable.__version__)'"
    Then the command exits with code 0
    And the output contains "0.1.0"
