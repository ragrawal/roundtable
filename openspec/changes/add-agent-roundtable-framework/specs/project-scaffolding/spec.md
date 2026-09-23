# Spec Delta

## Purpose

Turns an empty or existing directory into a roundtable review workspace, so a
user can go from nothing to a runnable multi-agent review with one command and
know exactly which agents will participate.

## ADDED Requirements

### Requirement: Workspace initialization

The `init` command SHALL create a review workspace in the target directory
containing an OpenSpec project layout, a Git repository, an empty event
store, a gitignored round-scratch directory, and an agent roster
configuration file. It SHALL gather the agent roster and round limit through
the interactive prompt sequence defined in "Interactive roster and
round-limit configuration", unless run non-interactively (see
"Non-interactive initialization via a config file"). On success it SHALL
report the created workspace path and the configured agent roster.

#### Scenario: Initializing an empty directory
- **WHEN** a user runs `init` in an empty directory
- **THEN** the command prompts for the agent roster and round limit, creates
  the OpenSpec project layout, initializes a Git repository with an initial
  commit, creates an empty event store and a gitignored round-scratch
  directory, and writes an agent roster configuration reflecting the
  prompted answers
- **AND** exits with code 0 reporting the workspace path and roster

#### Scenario: Initializing a directory that is already a Git repository
- **WHEN** a user runs `init` in a directory that already contains a Git
  repository
- **THEN** the command reuses the existing repository rather than
  reinitializing it, and creates the remaining workspace components
- **AND** leaves existing Git history and the working tree unmodified

### Requirement: Initialization refuses to overwrite an existing workspace

The `init` command SHALL NOT overwrite or delete an existing workspace. When
the target directory already contains a roundtable workspace, `init` SHALL
fail with a non-zero exit code and a message naming the conflicting path,
unless the user explicitly requests reinitialization.

#### Scenario: Target already contains a workspace
- **WHEN** a user runs `init` in a directory that already has a roundtable
  agent roster configuration
- **THEN** the command exits non-zero, names the conflicting file, and makes
  no changes to the directory

#### Scenario: Reinitialization is explicitly requested
- **WHEN** a user runs `init` with the reinitialize flag in a directory that
  already has a workspace
- **THEN** the command replaces the roster configuration and reports what it
  replaced
- **AND** preserves the existing event store and Git history

### Requirement: Prerequisite validation

The `init` command SHALL verify that its external prerequisites — a `git`
executable and a `herdr` executable of a supported version — are available
before making any filesystem changes. When a prerequisite is missing or
unsupported, it SHALL fail with a non-zero exit code and a message naming the
prerequisite and the requirement, and SHALL leave the target directory
unchanged.

#### Scenario: herdr is not installed
- **WHEN** a user runs `init` and no `herdr` executable is on `PATH`
- **THEN** the command exits non-zero with a message naming `herdr` as the
  missing prerequisite
- **AND** the target directory is unchanged

#### Scenario: herdr version is unsupported
- **WHEN** a user runs `init` and the installed `herdr` reports a major
  version the framework does not support
- **THEN** the command exits non-zero, reporting both the detected version and
  the supported range
- **AND** the target directory is unchanged

### Requirement: Agent roster configuration

The workspace SHALL declare its agent roster as configuration: exactly one
agent with the developer role, and one or more agents with the reviewer role,
each having a workspace-unique name, a role, and a prompt persona. The
framework SHALL reject a roster that has no developer, more than one
developer, or no reviewers, reporting which constraint was violated.

#### Scenario: Default suggestions when no existing configuration
- **WHEN** a user runs `init` in a directory with no existing
  `roundtable.toml` and accepts every prompt's default answer
- **THEN** the resulting roster contains one developer agent and two reviewer
  agents — a `product manager` persona and a `security reviewer` persona —
  each defaulting to the `claude` kind, and the round limit defaults to 3

#### Scenario: Roster is missing reviewers
- **WHEN** a review run starts from a roster containing only a developer agent
- **THEN** the run fails before any agent is started, reporting that at least
  one reviewer is required

#### Scenario: Roster has duplicate agent names
- **WHEN** a review run starts from a roster in which two agents share a name
- **THEN** the run fails before any agent is started, reporting the duplicated
  name

### Requirement: Interactive roster and round-limit configuration

The `init` command SHALL configure the agent roster and round limit through
an interactive prompt sequence: first the number of agents, then for each
agent a name, a role, a focus prompt, and an agent kind — the LLM that runs
it — chosen from a prepopulated list (including `claude` and `codex`) with
the option to enter a custom kind; finally the maximum number of review
rounds, defaulting to 3. Exactly one agent's role SHALL be `developer`; every
other configured agent acts as a reviewer, using its focus prompt as its
persona.

The role prompt SHALL offer a prepopulated list (including `developer`,
`product manager`, `senior engineer`, `security reviewer`, and `qa engineer`)
with the option to enter a custom role. Each predefined role SHALL have an
associated default focus prompt describing what that agent should pay
attention to when reviewing. When the user selects a predefined role, `init`
SHALL display that role's default focus prompt and offer it as the default
answer to the focus-prompt question, which the user may accept or override.
When the user enters a role that is not on the prepopulated list, there is no
default focus prompt: `init` SHALL prompt the user to write one for that
agent before moving to the next agent.

#### Scenario: Configuring a roster interactively
- **WHEN** a user runs `init` and enters an agent count of 3, then a name,
  role, focus prompt, and kind for each agent, then a round limit
- **THEN** the command writes a `roundtable.toml` with the three agents as
  entered and the entered round limit, deriving the developer/reviewer role
  from which agent's chosen role was `developer`

#### Scenario: Predefined role shows its default focus prompt
- **WHEN** a user selects the `security reviewer` role for an agent
- **THEN** the command displays that role's default focus prompt as the
  default answer to the focus-prompt question
- **AND** accepting the default uses that canned text as the agent's persona

#### Scenario: Overriding a predefined role's default focus prompt
- **WHEN** a user selects a predefined role and then edits the displayed
  default focus prompt instead of accepting it
- **THEN** the command uses the edited text as that agent's persona

#### Scenario: Custom role requires an authored focus prompt
- **WHEN** a user enters a role that is not on the prepopulated list
- **THEN** the command prompts the user to write a focus prompt for that
  agent, with no default offered
- **AND** uses the entered text as that agent's persona

#### Scenario: Choosing an agent kind not on the prepopulated list
- **WHEN** a user is prompted for an agent's kind and enters a value that is
  not in the prepopulated list
- **THEN** the command accepts it as that agent's kind

### Requirement: Non-interactive initialization via a config file

The `init` command SHALL support a non-interactive mode, given a path to a
config file already shaped like `roundtable.toml`, that supplies the full
agent roster and round limit without prompting. Interactive prompting SHALL
remain the default when no such file is given. A non-interactive roster that
violates roster validation SHALL be rejected the same way an interactively
built one would be, reporting the violated constraint, without prompting.

#### Scenario: Non-interactive init from a config file
- **WHEN** a user runs `init` with a path to a valid roster config file
- **THEN** the command uses that file's roster and round limit directly,
  prompts for nothing, and completes as the interactive path would

#### Scenario: Non-interactive config fails roster validation
- **WHEN** a user runs `init` with a path to a config file missing a
  developer agent
- **THEN** the command exits non-zero reporting that constraint, without
  prompting for anything

### Requirement: Existing configuration pre-populates prompts

When the target directory already contains a `roundtable.toml`, `init` SHALL
read it and present its agent count, each agent's name, role, focus prompt,
and kind, and its round limit as the default answer to the corresponding
prompt, so the user can reconfigure by accepting or overriding each value
rather than starting blank.

#### Scenario: Reinitializing pre-fills the previous configuration
- **WHEN** a user runs `init` with the reinitialize flag in a directory whose
  `roundtable.toml` has three agents and a round limit of 5
- **THEN** every prompt defaults to that agent's previous name, role, focus
  prompt, and kind, and the round-limit prompt defaults to 5
- **AND** accepting every default reproduces the same roster and round limit
