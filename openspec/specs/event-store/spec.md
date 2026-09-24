# event-store

## Purpose

Records every state change in a review run as a validated, append-only event
log, so a run's history is auditable and a malformed payload from an agent is
rejected at the boundary instead of becoming corrupt history.

## Requirements

### Requirement: Common event envelope

Every recorded event SHALL carry an envelope with a unique event identifier, a
timestamp, the identifier of the specification under review, the event type,
and the identifier of the agent or component that emitted it. An event missing
any envelope field SHALL be rejected.

#### Scenario: Well-formed envelope is accepted
- **WHEN** an event is submitted with all envelope fields present and valid
- **THEN** the event is appended to the store and its identifier is returned

#### Scenario: Envelope is missing a field
- **WHEN** an event is submitted without a specification identifier
- **THEN** the submission is rejected naming the missing field, and nothing is
  appended to the store

#### Scenario: Event identifiers are unique
- **WHEN** an event is submitted whose identifier already exists in the store
- **THEN** the submission is rejected as a duplicate, and the stored event is
  left unchanged

### Requirement: Typed event payloads

The store SHALL accept exactly these event types, each with its required
payload fields:

- `ArtifactDrafted` — the draft's version identifier (a Git state identifier)
  and its content, a summary suitable for a reviewer prompt. For a spec-phase
  draft, content is the full OpenSpec change text; for a code-phase draft,
  content is a diff or file-change summary rather than the full multi-file
  diff — the version identifier is the canonical reference for the complete,
  multi-file state
- `CritiqueSubmitted` — a review identifier, the targeted section, a severity,
  an issue description, and an optional suggested patch
- `RevisionRequested` — a discussion identifier and the revision notes
- `ConsensusDeadlocked` — a discussion identifier, the opposing viewpoints,
  the trade-offs, and the targeted section
- `ConsensusReached` — a discussion identifier, the approving signatures, and
  the final state identifier

An event of an unrecognized type, or of a known type missing a required
payload field, SHALL be rejected.

#### Scenario: Critique payload is complete
- **WHEN** a `CritiqueSubmitted` event is submitted with a review identifier,
  target section, severity, and issue description
- **THEN** the event is appended to the store

#### Scenario: Critique payload has an invalid severity
- **WHEN** a `CritiqueSubmitted` event is submitted with a severity outside
  the permitted set
- **THEN** the submission is rejected naming the severity field and the
  permitted values, and nothing is appended

#### Scenario: Unknown event type
- **WHEN** an event of an unrecognized type is submitted
- **THEN** the submission is rejected naming the unrecognized type, and
  nothing is appended

#### Scenario: Unexpected extra payload field
- **WHEN** an event is submitted carrying a payload field its type does not
  define
- **THEN** the submission is rejected naming the unexpected field, and nothing
  is appended

### Requirement: Validation precedes persistence

The store SHALL validate an event completely before any part of it is
persisted. A rejected event SHALL leave the store byte-for-byte unchanged, and
SHALL NOT be partially written or repaired by defaulting missing fields.

#### Scenario: Rejected event leaves the store unchanged
- **WHEN** an invalid event is submitted to a store holding three events
- **THEN** the submission is rejected and the store still holds exactly those
  three events, unchanged

#### Scenario: Missing fields are not defaulted
- **WHEN** an event is submitted with a required payload field absent
- **THEN** the submission is rejected rather than persisted with a substituted
  value

### Requirement: Append-only ordering

The store SHALL be append-only: recorded events SHALL NOT be modified or
deleted through the store's interface, and reads SHALL return events in the
order they were appended. A correction SHALL be expressed as a new event
rather than an edit to an existing one.

#### Scenario: Read order matches append order
- **WHEN** four events are appended in sequence and then read back
- **THEN** they are returned in the same order they were appended

#### Scenario: No interface for mutation
- **WHEN** a caller attempts to alter or remove an already-appended event
- **THEN** the store provides no operation that does so, and the stored event
  is unchanged

### Requirement: Replay by specification

The store SHALL support reading back the full, ordered event sequence for a
given specification identifier, so a run's progression can be replayed
independently of the agents that produced it. Replay SHALL exclude events
belonging to other specifications.

#### Scenario: Replaying one specification's events
- **WHEN** a store holds events for two different specifications and a caller
  replays one of them
- **THEN** only that specification's events are returned, in append order

#### Scenario: Replaying a specification with no events
- **WHEN** a caller replays a specification identifier that has no events
- **THEN** an empty sequence is returned rather than an error

### Requirement: Concurrent append safety

The store's append operation SHALL be safe to call from multiple threads
concurrently. Concurrent appends SHALL be serialized so that no two events'
data interleave or corrupt one another, and each appended event SHALL be
durably recorded as one complete, valid record before the append call
returns.

#### Scenario: Concurrent critique events append cleanly
- **WHEN** multiple threads call append concurrently, each with a different
  `CritiqueSubmitted` event for the same specification
- **THEN** every event is durably recorded as a complete, valid record with
  no interleaved or corrupted data
- **AND** all events are present, each as its own record, once every call
  returns

### Requirement: Store survives process restart

Recorded events SHALL persist across process restarts. A store reopened after
the process that wrote it has exited SHALL return the same events, in the same
order, as before the restart.

#### Scenario: Events outlive the writing process
- **WHEN** events are appended, the process exits, and the store is reopened
- **THEN** reading the store returns the previously appended events in their
  original order
