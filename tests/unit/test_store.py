"""Unit tests for roundtable.store.JsonlEventStore."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from roundtable.events import (
    ArtifactDrafted,
    ConsensusReached,
    CritiqueFinding,
    CritiqueSubmitted,
    RoundtableEventAdapter,
    Severity,
)
from roundtable.store import DuplicateEventError, JsonlEventStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _drafted(specification_id: str = "spec-1", **overrides: object) -> ArtifactDrafted:
    fields = {
        "timestamp": NOW,
        "specification_id": specification_id,
        "emitter": "developer",
        "version_id": "abc123",
        "content": "draft text",
    }
    fields.update(overrides)
    return ArtifactDrafted(**fields)


def _critique(specification_id: str = "spec-1", **overrides: object) -> CritiqueSubmitted:
    fields = {
        "timestamp": NOW,
        "specification_id": specification_id,
        "emitter": "security",
        "review_id": "round-1",
        "finding": CritiqueFinding(
            target_section="Requirement: Foo",
            severity=Severity.BLOCKING,
            description="Missing edge case.",
        ),
    }
    fields.update(overrides)
    return CritiqueSubmitted(**fields)


def test_replay_returns_events_in_append_order(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    events = [
        _drafted(),
        _critique(),
        _critique(review_id="round-2"),
        _critique(review_id="round-3"),
    ]
    for event in events:
        store.append(event)

    replayed = store.replay("spec-1")

    assert [e.event_id for e in replayed] == [e.event_id for e in events]


def test_duplicate_event_id_is_rejected_and_store_unchanged(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    event = _drafted()
    store.append(event)

    with pytest.raises(DuplicateEventError):
        store.append(event)

    assert [e.event_id for e in store.replay("spec-1")] == [event.event_id]


def test_invalid_event_leaves_store_byte_for_byte_unchanged(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    for event in (_drafted(), _critique(), _critique(review_id="round-2")):
        store.append(event)
    path = tmp_path / "spec-1.jsonl"
    before = path.read_bytes()

    with pytest.raises(ValidationError):
        RoundtableEventAdapter.validate_python(
            {
                "timestamp": NOW.isoformat(),
                "specification_id": "spec-1",
                "emitter": "developer",
                "event_type": "ArtifactDrafted",
                # version_id is missing; must be rejected, not defaulted
                "content": "draft text",
            }
        )

    assert path.read_bytes() == before


def test_replay_isolates_specifications(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    store.append(_drafted(specification_id="spec-a"))
    store.append(_drafted(specification_id="spec-b"))
    store.append(_critique(specification_id="spec-a"))

    replayed_a = store.replay("spec-a")

    assert all(e.specification_id == "spec-a" for e in replayed_a)
    assert len(replayed_a) == 2


def test_replay_of_unknown_specification_returns_empty_sequence(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)

    assert store.replay("never-seen") == []


def test_store_survives_restart(tmp_path: Path) -> None:
    first = JsonlEventStore(tmp_path)
    events = [_drafted(), _critique()]
    for event in events:
        first.append(event)

    reopened = JsonlEventStore(tmp_path)

    assert [e.event_id for e in reopened.replay("spec-1")] == [e.event_id for e in events]


def test_reopened_store_still_rejects_duplicate_ids_seen_before_restart(tmp_path: Path) -> None:
    first = JsonlEventStore(tmp_path)
    event = _drafted()
    first.append(event)

    reopened = JsonlEventStore(tmp_path)

    with pytest.raises(DuplicateEventError):
        reopened.append(event)


def test_latest_of_type_returns_the_most_recent_match(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    store.append(_drafted())
    first_consensus = ConsensusReached(
        timestamp=NOW,
        specification_id="spec-1",
        emitter="framework",
        discussion_id="round-1",
        approving_reviewers=["security"],
        final_state_id="abc123",
    )
    second_consensus = ConsensusReached(
        timestamp=NOW,
        specification_id="spec-1",
        emitter="framework",
        discussion_id="round-2",
        approving_reviewers=["security", "qa"],
        final_state_id="def456",
    )
    store.append(first_consensus)
    store.append(second_consensus)

    latest = store.latest_of_type("spec-1", ConsensusReached)

    assert latest is not None
    assert latest.event_id == second_consensus.event_id


def test_concurrent_appends_produce_no_interleaved_or_corrupted_lines(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path)
    events = [_critique(review_id=f"round-{i}") for i in range(50)]

    threads = [threading.Thread(target=store.append, args=(event,)) for event in events]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    path = tmp_path / "spec-1.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == len(events)
    for line in lines:
        json.loads(line)  # each line is a single, complete, valid JSON object
    assert {e.event_id for e in store.replay("spec-1")} == {e.event_id for e in events}
