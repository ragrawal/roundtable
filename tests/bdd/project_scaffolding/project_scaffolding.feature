Feature: Project scaffolding
  `roundtable init` turns a directory into a review workspace: OpenSpec
  layout, Git repository, event store, gitignored scratch directory, and an
  agent roster configuration.

  Scenario: Initializing an empty directory non-interactively
    Given a temporary directory
    And herdr is available
    And a roster config file "roster.toml" with a developer and a security reviewer and a round limit of 2
    When the user runs "roundtable init {tmp_dir} --config {tmp_dir}/roster.toml"
    Then the command exits with code 0
    And the following files exist: {tmp_dir}/roundtable.toml
    And the following directories exist: {tmp_dir}/.roundtable/events, {tmp_dir}/.roundtable/scratch, {tmp_dir}/openspec
    And the file "{tmp_dir}/.gitignore" contains ".roundtable/scratch/"
    And the file "{tmp_dir}/roundtable.toml" contains "round_limit = 2"

  Scenario: init refuses to overwrite an existing workspace
    Given a temporary directory
    And herdr is available
    And a roundtable workspace is already initialized there
    And a roster config file "roster.toml" with a developer and a security reviewer and a round limit of 2
    When the user runs "roundtable init {tmp_dir} --config {tmp_dir}/roster.toml"
    Then the command exits with a non-zero code
    And the output contains "already exists"

  Scenario: init fails when herdr is not installed, leaving the directory unchanged
    Given a temporary directory
    And herdr is not installed
    And a roster config file "roster.toml" with a developer and a security reviewer and a round limit of 2
    When the user runs "roundtable init {tmp_dir} --config {tmp_dir}/roster.toml"
    Then the command exits with a non-zero code
    And the output contains "herdr"
    And the following files do not exist: {tmp_dir}/roundtable.toml
