"""Step definitions for exercising the roundtable web UI's backend end-to-end."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    CritiqueFinding,
    CritiqueSubmitted,
    OpposingViewpoint,
    Severity,
)
from roundtable.store import SqliteEventStore
from roundtable.web.app import create_app

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MAX_POLL_ATTEMPTS = 8


@dataclass
class WebUiContext:
    """Shared state threaded through a single BDD scenario's steps."""

    workspace_root: Path
    store: SqliteEventStore
    client: TestClient
    response: Any = None
    websocket: Any = None
    received_events: list[dict] = field(default_factory=list)
    lock_fd: int | None = None


def _drafted(specification_id: str, **overrides: str) -> ArtifactDrafted:
    fields = {
        "timestamp": NOW,
        "specification_id": specification_id,
        "emitter": "dev",
        "version_id": "sha-1",
        "content": "a summary",
    }
    fields.update(overrides)
    return ArtifactDrafted(**fields)


def _critique(specification_id: str, *, review_id: str = "1") -> CritiqueSubmitted:
    return CritiqueSubmitted(
        timestamp=NOW,
        specification_id=specification_id,
        emitter="sec",
        review_id=review_id,
        finding=CritiqueFinding(
            target_section="intro", severity=Severity.BLOCKING, description="fix this"
        ),
    )


def _deadlocked(specification_id: str, *, discussion_id: str = "1") -> ConsensusDeadlocked:
    return ConsensusDeadlocked(
        timestamp=NOW,
        specification_id=specification_id,
        emitter="framework",
        discussion_id=discussion_id,
        target_section="intro",
        opposing_viewpoints=[OpposingViewpoint(agent="sec", position="no")],
        trade_offs="tradeoffs",
    )


def _save_current_roster(context: WebUiContext) -> None:
    current = context.client.get("/api/roster").json()
    context.response = context.client.put("/api/roster", json={"agents": current["agents"]})


def _receive_until_matching(websocket: Any, event_type: str) -> dict:
    for _ in range(MAX_POLL_ATTEMPTS):
        message = websocket.receive_json()
        if any(event["event_type"] == event_type for event in message["events"]):
            return message
    raise AssertionError(f"No {event_type} event received within {MAX_POLL_ATTEMPTS} polls.")


@given(
    parsers.parse('a workspace with a roundtable.toml roster of "{developer}" and "{reviewer}"'),
    target_fixture="web_ui_context",
)
def given_workspace(tmp_path: Path, developer: str, reviewer: str) -> WebUiContext:
    config = RoundtableConfig(
        roster=AgentRoster(
            agents=[
                AgentProfile(
                    name=developer, role="developer", persona="Write the code.", kind="claude"
                ),
                AgentProfile(
                    name=reviewer, role="security reviewer", persona="Find bugs.", kind="claude"
                ),
            ]
        )
    )
    (tmp_path / "roundtable.toml").write_text(tomli_w.dumps(config.model_dump(mode="json")))
    store = SqliteEventStore(tmp_path / "events.db")
    return WebUiContext(workspace_root=tmp_path, store=store, client=None)  # type: ignore[arg-type]


@given("the web UI app is running for that workspace")
def given_app_running(web_ui_context: WebUiContext) -> None:
    app = create_app(web_ui_context.workspace_root, store=web_ui_context.store)
    web_ui_context.client = TestClient(app)


@when(parsers.parse('the operator edits "{name}"\'s persona to "{persona}" and saves'))
def when_operator_edits_persona(web_ui_context: WebUiContext, name: str, persona: str) -> None:
    current = web_ui_context.client.get("/api/roster").json()
    for agent in current["agents"]:
        if agent["name"] == name:
            agent["persona"] = persona
    web_ui_context.response = web_ui_context.client.put(
        "/api/roster", json={"agents": current["agents"]}
    )


@then("the save succeeds")
def then_save_succeeds(web_ui_context: WebUiContext) -> None:
    assert web_ui_context.response.status_code == 200


@then(parsers.parse('the roster read back shows "{name}" with persona "{persona}"'))
def then_roster_shows_persona(web_ui_context: WebUiContext, name: str, persona: str) -> None:
    body = web_ui_context.client.get("/api/roster").json()
    agent = next(agent for agent in body["agents"] if agent["name"] == name)
    assert agent["persona"] == persona


@then("the round_limit is unchanged")
def then_round_limit_unchanged(web_ui_context: WebUiContext) -> None:
    body = web_ui_context.client.get("/api/roster").json()
    assert body["round_limit"] == RoundtableConfig.model_fields["round_limit"].default


@given("another session is already holding the roster lock")
def given_lock_held(web_ui_context: WebUiContext) -> None:
    lock_path = web_ui_context.workspace_root / "roundtable.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    web_ui_context.lock_fd = fd


@when("the operator saves a roster edit")
def when_operator_saves_edit(web_ui_context: WebUiContext) -> None:
    _save_current_roster(web_ui_context)


@then("the save is denied as locked")
def then_save_denied_locked(web_ui_context: WebUiContext) -> None:
    assert web_ui_context.response.status_code == 409


@when("the other session releases the roster lock")
def when_lock_released(web_ui_context: WebUiContext) -> None:
    assert web_ui_context.lock_fd is not None
    fcntl.flock(web_ui_context.lock_fd, fcntl.LOCK_UN)
    os.close(web_ui_context.lock_fd)
    web_ui_context.lock_fd = None


@when("the operator saves the same roster edit again")
def when_operator_saves_again(web_ui_context: WebUiContext) -> None:
    _save_current_roster(web_ui_context)


@given(
    parsers.parse('an operator is watching the event feed for specification "{specification_id}"')
)
def given_watching_feed(
    web_ui_context: WebUiContext, specification_id: str, request: pytest.FixtureRequest
) -> None:
    connection = web_ui_context.client.websocket_connect(
        f"/ws/specifications/{specification_id}/events"
    )
    web_ui_context.websocket = connection.__enter__()
    request.addfinalizer(lambda: connection.__exit__(None, None, None))


@when(parsers.parse('a draft is appended for specification "{specification_id}"'))
def when_draft_appended(web_ui_context: WebUiContext, specification_id: str) -> None:
    web_ui_context.store.append(_drafted(specification_id))


@then("the feed delivers the draft event")
def then_feed_delivers_draft(web_ui_context: WebUiContext) -> None:
    message = _receive_until_matching(web_ui_context.websocket, "ArtifactDrafted")
    web_ui_context.received_events.extend(message["events"])


@when(parsers.parse('a critique is appended for specification "{specification_id}"'))
def when_critique_appended(web_ui_context: WebUiContext, specification_id: str) -> None:
    web_ui_context.store.append(_critique(specification_id))


@then("the feed delivers the critique event")
def then_feed_delivers_critique(web_ui_context: WebUiContext) -> None:
    message = _receive_until_matching(web_ui_context.websocket, "CritiqueSubmitted")
    web_ui_context.received_events.extend(message["events"])


@then("no event is delivered twice")
def then_no_event_delivered_twice(web_ui_context: WebUiContext) -> None:
    event_ids = [event["event_id"] for event in web_ui_context.received_events]
    assert len(event_ids) == len(set(event_ids))


@given(parsers.parse('specification "{specification_id}" has reached a deadlock'))
def given_deadlock(web_ui_context: WebUiContext, specification_id: str) -> None:
    web_ui_context.store.append(_drafted(specification_id))
    web_ui_context.store.append(_critique(specification_id, review_id="1"))
    web_ui_context.store.append(_deadlocked(specification_id, discussion_id="1"))


@then(parsers.parse('the status for "{specification_id}" shows outcome "{outcome}"'))
def then_status_shows_outcome(
    web_ui_context: WebUiContext, specification_id: str, outcome: str
) -> None:
    body = web_ui_context.client.get(f"/api/specifications/{specification_id}/status").json()
    assert body["outcome_label"] == outcome


@when(
    parsers.parse(
        'a critique resuming the round is appended for specification "{specification_id}"'
    )
)
def when_resuming_critique_appended(web_ui_context: WebUiContext, specification_id: str) -> None:
    web_ui_context.store.append(_critique(specification_id, review_id="2"))
