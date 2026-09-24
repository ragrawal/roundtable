"""Unit tests for round grouping, filtering, version listing, and lifecycle status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    ConsensusReached,
    CritiqueFinding,
    CritiqueSubmitted,
    OpposingViewpoint,
    RevisionRequested,
    Severity,
)
from roundtable.store import SqliteEventStore
from roundtable.web.app import create_app
from roundtable.web.event_feed import filter_events, group_by_round, list_versions
from roundtable.web.status import (
    ConnectionHealth,
    OutcomeLabel,
    derive_connection_health,
    derive_outcome_label,
)

SPEC_ID = "spec-1"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _drafted(
    *, version_id: str = "v1", emitter: str = "dev", timestamp: datetime = NOW
) -> ArtifactDrafted:
    return ArtifactDrafted(
        timestamp=timestamp,
        specification_id=SPEC_ID,
        emitter=emitter,
        version_id=version_id,
        content="a summary",
    )


def _critique(
    *, review_id: str = "1", emitter: str = "reviewer", timestamp: datetime = NOW
) -> CritiqueSubmitted:
    return CritiqueSubmitted(
        timestamp=timestamp,
        specification_id=SPEC_ID,
        emitter=emitter,
        review_id=review_id,
        finding=CritiqueFinding(
            target_section="intro", severity=Severity.BLOCKING, description="fix this"
        ),
    )


def _revision_requested(
    *, discussion_id: str = "1", timestamp: datetime = NOW
) -> RevisionRequested:
    return RevisionRequested(
        timestamp=timestamp,
        specification_id=SPEC_ID,
        emitter="framework",
        discussion_id=discussion_id,
        blocking_critiques=[
            CritiqueFinding(
                target_section="intro", severity=Severity.BLOCKING, description="fix this"
            )
        ],
    )


def _deadlocked(*, discussion_id: str = "1", timestamp: datetime = NOW) -> ConsensusDeadlocked:
    return ConsensusDeadlocked(
        timestamp=timestamp,
        specification_id=SPEC_ID,
        emitter="framework",
        discussion_id=discussion_id,
        target_section="intro",
        opposing_viewpoints=[OpposingViewpoint(agent="reviewer", position="no")],
        trade_offs="tradeoffs",
    )


def _consensus(*, discussion_id: str = "1", timestamp: datetime = NOW) -> ConsensusReached:
    return ConsensusReached(
        timestamp=timestamp,
        specification_id=SPEC_ID,
        emitter="framework",
        discussion_id=discussion_id,
        approving_reviewers=["reviewer"],
        final_state_id="v1",
    )


# -- group_by_round -----------------------------------------------------------------


def test_first_draft_is_grouped_into_round_one() -> None:
    draft = _drafted()
    rounds = group_by_round([draft])

    assert rounds == {"1": [draft]}


def test_critique_submitted_is_grouped_by_its_review_id() -> None:
    draft = _drafted()
    critique = _critique(review_id="1")

    rounds = group_by_round([draft, critique])

    assert rounds["1"] == [draft, critique]


def test_draft_following_a_revision_request_joins_the_next_round() -> None:
    critique = _critique(review_id="1")
    revision = _revision_requested(discussion_id="1")
    second_draft = _drafted(version_id="v2")

    rounds = group_by_round([critique, revision, second_draft])

    assert rounds["1"] == [critique, revision]
    assert rounds["2"] == [second_draft]


# -- filter_events --------------------------------------------------------------------


def test_filter_events_by_emitter() -> None:
    draft = _drafted(emitter="dev")
    critique = _critique(emitter="reviewer")
    events = [draft, critique]
    rounds = group_by_round(events)

    assert filter_events(events, rounds, emitter="reviewer") == [critique]


def test_filter_events_by_event_type() -> None:
    draft = _drafted()
    critique = _critique()
    events = [draft, critique]
    rounds = group_by_round(events)

    assert filter_events(events, rounds, event_type="ArtifactDrafted") == [draft]


def test_filter_events_by_round_number() -> None:
    critique = _critique(review_id="1")
    revision = _revision_requested(discussion_id="1")
    second_draft = _drafted(version_id="v2")
    events = [critique, revision, second_draft]
    rounds = group_by_round(events)

    assert filter_events(events, rounds, round_number="2") == [second_draft]


def test_filter_events_by_keyword_is_case_insensitive() -> None:
    draft = _drafted()
    events = [draft]
    rounds = group_by_round(events)

    assert filter_events(events, rounds, keyword="SUMMARY") == [draft]
    assert filter_events(events, rounds, keyword="nonexistent") == []


# -- list_versions ----------------------------------------------------------------------


def test_list_versions_returns_only_artifact_drafted_events_in_order() -> None:
    first = _drafted(version_id="v1")
    critique = _critique()
    second = _drafted(version_id="v2")

    versions = list_versions([first, critique, second])

    assert [version.version_id for version in versions] == ["v1", "v2"]
    assert versions[0].content == "a summary"


# -- derive_outcome_label -----------------------------------------------------------------


@pytest.mark.parametrize(
    "events",
    [
        pytest.param([], id="no-events-recorded-yet"),
    ],
)
def test_outcome_label_is_no_history_on_empty_replay(events: list) -> None:
    # An empty `replay` result is indistinguishable between "a first draft
    # turn is actively in progress" and "a failed first draft already ended
    # the run with nothing recorded" — both must read as this label, which
    # deliberately says "may be drafting" rather than implying nothing ever
    # started.
    assert derive_outcome_label(events) == OutcomeLabel.NO_HISTORY


def test_outcome_label_is_consensus_reached_only_on_a_consensus_reached_tail() -> None:
    events = [_drafted(), _critique(), _consensus()]

    assert derive_outcome_label(events) == OutcomeLabel.CONSENSUS_REACHED


def test_outcome_label_stays_consensus_reached_after_connection_health_flips_to_disconnected() -> (
    None
):
    events = [_drafted(), _critique(), _consensus()]

    assert derive_outcome_label(events) == OutcomeLabel.CONSENSUS_REACHED
    assert (
        derive_connection_health(connected=False, events=events, now=NOW)
        == ConnectionHealth.DISCONNECTED
    )
    assert derive_outcome_label(events) == OutcomeLabel.CONSENSUS_REACHED


def test_outcome_label_is_deadlocked_not_complete_on_a_deadlocked_tail() -> None:
    events = [_drafted(), _critique(), _deadlocked()]

    assert derive_outcome_label(events) == OutcomeLabel.DEADLOCKED


def test_outcome_label_is_deadlocked_together_with_a_stale_connection() -> None:
    events = [_drafted(), _critique(), _deadlocked(timestamp=NOW)]
    later = NOW + timedelta(minutes=5)

    assert derive_outcome_label(events) == OutcomeLabel.DEADLOCKED
    assert (
        derive_connection_health(connected=True, events=events, now=later) == ConnectionHealth.STALE
    )


def test_outcome_label_transitions_to_in_progress_after_a_post_deadlock_critique() -> None:
    events = [_drafted(), _critique(), _deadlocked(), _critique(review_id="2")]

    assert derive_outcome_label(events) == OutcomeLabel.IN_PROGRESS


# -- derive_connection_health -------------------------------------------------------------


def test_connection_health_on_empty_replay_is_live_when_connected() -> None:
    assert derive_connection_health(connected=True, events=[], now=NOW) == ConnectionHealth.LIVE


def test_connection_health_on_empty_replay_is_disconnected_when_not_connected() -> None:
    assert (
        derive_connection_health(connected=False, events=[], now=NOW)
        == ConnectionHealth.DISCONNECTED
    )


def test_connection_health_is_never_stale_on_an_empty_replay_result() -> None:
    far_future = NOW + timedelta(days=1)

    assert (
        derive_connection_health(connected=True, events=[], now=far_future) == ConnectionHealth.LIVE
    )


def test_stale_and_disconnected_are_computed_independently() -> None:
    events = [_drafted(timestamp=NOW)]
    stale_time = NOW + timedelta(minutes=5)

    assert (
        derive_connection_health(connected=True, events=events, now=stale_time)
        == ConnectionHealth.STALE
    )
    # A disconnected transport is DISCONNECTED regardless of how recent the
    # last event was, even one that would otherwise still read as live.
    assert (
        derive_connection_health(connected=False, events=events, now=NOW)
        == ConnectionHealth.DISCONNECTED
    )


# -- WebSocket dedup --------------------------------------------------------------------


def test_websocket_feed_does_not_resend_an_already_delivered_event(tmp_path: Path) -> None:
    store = SqliteEventStore(tmp_path / "events.db")
    store.append(_drafted(version_id="v1"))
    app = create_app(tmp_path, store=store)
    client = TestClient(app)

    with client.websocket_connect(f"/ws/specifications/{SPEC_ID}/events") as websocket:
        first_message = websocket.receive_json()
        assert [event["version_id"] for event in first_message["events"]] == ["v1"]

        store.append(_critique())

        second_message = websocket.receive_json()
        assert len(second_message["events"]) == 1
        assert second_message["events"][0]["event_type"] == "CritiqueSubmitted"
