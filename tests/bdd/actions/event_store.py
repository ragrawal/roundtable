"""Step definitions for exercising `roundtable.store.JsonlEventStore` end-to-end."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from pytest_bdd import given, parsers, then, when

from roundtable.events import ArtifactDrafted, RoundtableEvent, RoundtableEventAdapter
from roundtable.store import DuplicateEventError, JsonlEventStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class EventStoreContext:
    root: Path
    store: JsonlEventStore
    appended: list[RoundtableEvent] = field(default_factory=list)
    last_error: Exception | None = None


def _drafted(specification_id: str, **overrides: object) -> ArtifactDrafted:
    fields = {
        "timestamp": NOW,
        "specification_id": specification_id,
        "emitter": "developer",
        "version_id": "abc123",
        "content": "draft text",
    }
    fields.update(overrides)
    return ArtifactDrafted(**fields)


@given("an empty event store", target_fixture="event_store_context")
def given_empty_event_store(tmp_path: Path) -> EventStoreContext:
    return EventStoreContext(root=tmp_path, store=JsonlEventStore(tmp_path))


@when(parsers.parse('{count:d} drafts are appended for "{specification_id}"'))
def when_drafts_are_appended(
    event_store_context: EventStoreContext, count: int, specification_id: str
) -> None:
    for i in range(count):
        event = _drafted(specification_id, version_id=f"sha-{i}", content=f"draft {i}")
        event_store_context.store.append(event)
        event_store_context.appended.append(event)


@when("the first appended event is appended again")
def when_first_appended_event_is_appended_again(event_store_context: EventStoreContext) -> None:
    try:
        event_store_context.store.append(event_store_context.appended[0])
    except DuplicateEventError as exc:
        event_store_context.last_error = exc


@when(parsers.parse('a critique with severity "{severity}" is submitted for "{specification_id}"'))
def when_invalid_critique_submitted(
    event_store_context: EventStoreContext, severity: str, specification_id: str
) -> None:
    raw = {
        "event_type": "CritiqueSubmitted",
        "timestamp": NOW.isoformat(),
        "specification_id": specification_id,
        "emitter": "security",
        "review_id": "round-1",
        "finding": {
            "target_section": "Auth",
            "severity": severity,
            "description": "Missing edge case.",
        },
    }
    try:
        event = RoundtableEventAdapter.validate_python(raw)
    except ValidationError as exc:
        event_store_context.last_error = exc
        return
    event_store_context.store.append(event)
    event_store_context.appended.append(event)


@when("the store is reopened")
def when_store_is_reopened(event_store_context: EventStoreContext) -> None:
    event_store_context.store = JsonlEventStore(event_store_context.root)


@then(parsers.parse('replaying "{specification_id}" returns {count:d} events in order'))
def then_replaying_returns_events_in_order(
    event_store_context: EventStoreContext, specification_id: str, count: int
) -> None:
    replayed = event_store_context.store.replay(specification_id)
    assert len(replayed) == count
    expected_ids = [
        event.event_id
        for event in event_store_context.appended
        if event.specification_id == specification_id
    ]
    assert [event.event_id for event in replayed] == expected_ids


@then(parsers.parse('the submission is rejected naming the "{field_name}" field'))
def then_submission_rejected_naming_field(
    event_store_context: EventStoreContext, field_name: str
) -> None:
    assert event_store_context.last_error is not None
    assert field_name in str(event_store_context.last_error)


@then("the submission is rejected as a duplicate")
def then_submission_rejected_as_duplicate(event_store_context: EventStoreContext) -> None:
    assert isinstance(event_store_context.last_error, DuplicateEventError)
