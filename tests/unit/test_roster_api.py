"""Unit tests for the roster read/write API and its advisory-lock protocol."""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest
import tomli_w
from fastapi.testclient import TestClient

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.web.app import create_app
from roundtable.web.lock import RosterLockedError, roster_lock

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
REVIEWER = AgentProfile(name="rev", role="security reviewer", persona="Find bugs.", kind="claude")


def _write_config(path: Path, *, round_limit: int = 3) -> None:
    config = RoundtableConfig(
        roster=AgentRoster(agents=[DEVELOPER, REVIEWER]), round_limit=round_limit
    )
    path.write_text(tomli_w.dumps(config.model_dump(mode="json")))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    _write_config(tmp_path / "roundtable.toml")
    return tmp_path


@pytest.fixture
def client(workspace: Path) -> TestClient:
    return TestClient(create_app(workspace))


def test_get_roster_returns_current_agents_and_round_limit(client: TestClient) -> None:
    response = client.get("/api/roster")

    assert response.status_code == 200
    body = response.json()
    assert {agent["name"] for agent in body["agents"]} == {"dev", "rev"}
    assert body["round_limit"] == 3


def test_save_roster_rejects_missing_developer(client: TestClient) -> None:
    response = client.put("/api/roster", json={"agents": [REVIEWER.model_dump()]})

    assert response.status_code == 422
    assert "developer" in response.json()["detail"]


def test_save_roster_rejects_multiple_developers(client: TestClient) -> None:
    second_developer = DEVELOPER.model_copy(update={"name": "dev2"})
    response = client.put(
        "/api/roster",
        json={
            "agents": [DEVELOPER.model_dump(), second_developer.model_dump(), REVIEWER.model_dump()]
        },
    )

    assert response.status_code == 422
    assert "exactly one developer" in response.json()["detail"]


def test_save_roster_rejects_duplicate_names(client: TestClient) -> None:
    duplicate = REVIEWER.model_copy(update={"name": "dev"})
    response = client.put(
        "/api/roster", json={"agents": [DEVELOPER.model_dump(), duplicate.model_dump()]}
    )

    assert response.status_code == 422
    assert "unique" in response.json()["detail"]


def test_save_roster_rejects_bad_name_pattern(client: TestClient) -> None:
    response = client.put(
        "/api/roster",
        json={"agents": [DEVELOPER.model_dump(), {**REVIEWER.model_dump(), "name": "Bad-Name!"}]},
    )

    assert response.status_code == 422


def test_save_roster_preserves_round_limit_when_not_specified(client: TestClient) -> None:
    edited = REVIEWER.model_copy(update={"persona": "New focus."})
    response = client.put(
        "/api/roster", json={"agents": [DEVELOPER.model_dump(), edited.model_dump()]}
    )

    assert response.status_code == 200
    assert response.json()["round_limit"] == 3


def test_save_roster_applies_an_explicit_round_limit_change(client: TestClient) -> None:
    response = client.put(
        "/api/roster",
        json={"agents": [DEVELOPER.model_dump(), REVIEWER.model_dump()], "round_limit": 5},
    )

    assert response.status_code == 200
    assert response.json()["round_limit"] == 5


def test_second_acquirer_is_denied_while_first_holds_the_lock(workspace: Path) -> None:
    with roster_lock(workspace), pytest.raises(RosterLockedError):
        with roster_lock(workspace):
            pass


def _acquire_lock_and_sleep(workspace_str: str) -> None:
    import fcntl

    lock_file = Path(workspace_str) / "roundtable.lock"
    file_descriptor = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(file_descriptor, fcntl.LOCK_EX)
    time.sleep(60)


def test_lock_is_released_immediately_when_the_holding_process_dies(workspace: Path) -> None:
    process = multiprocessing.get_context("fork").Process(
        target=_acquire_lock_and_sleep, args=(str(workspace),)
    )
    process.start()
    try:
        time.sleep(0.3)  # let the child acquire the lock

        with pytest.raises(RosterLockedError):
            with roster_lock(workspace):
                pass

        process.kill()  # SIGKILL: no cleanup handler runs, no lock release code executes
        process.join(timeout=5)

        # Reacquire immediately, well before any staleness timeout: the OS,
        # not an age check, released the lock when the process died.
        with roster_lock(workspace):
            pass
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
