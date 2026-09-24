# Spec Delta

## MODIFIED Requirements

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
