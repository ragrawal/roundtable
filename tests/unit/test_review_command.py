"""Unit tests for roundtable.review_command.execute_review: the review command's shared shell."""

from __future__ import annotations

import json
from pathlib import Path

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.events import ConsensusDeadlocked, ConsensusReached
from roundtable.review_command import (
    EXIT_CONSENSUS,
    EXIT_DEADLOCK,
    EXIT_ORCHESTRATION_FAILURE,
    execute_review,
)
from roundtable.store import JsonlEventStore
from roundtable.workspace import events_root, write_config
from tests.unit.test_review_runner import FakeHerdrClient, _init_git_repo

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)


def _setup_workspace(tmp_path: Path, round_limit: int = 1) -> None:
    config = RoundtableConfig(
        roster=AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER]), round_limit=round_limit
    )
    write_config(tmp_path, config)
    _init_git_repo(tmp_path)


def _respond_with(herdr: FakeHerdrClient, workspace_root: Path, sec_findings: list[dict]) -> None:
    call_counts = {"dev": 0, "sec": 0}

    def respond(target: str, text: str) -> None:
        del text
        agent = next(name for name, pane in herdr.started_agents.items() if pane == target)
        call_counts[agent] += 1
        result_path = (
            workspace_root / ".roundtable" / "scratch" / str(call_counts[agent]) / f"{agent}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            result_path.write_text(json.dumps({"summary": "the draft"}))
        else:
            result_path.write_text(json.dumps({"findings": sec_findings}))

    herdr.respond = respond


def test_execute_review_returns_exit_consensus_and_records_consensus_reached(
    tmp_path: Path, capsys: object
) -> None:
    _setup_workspace(tmp_path)
    herdr = FakeHerdrClient()
    _respond_with(herdr, tmp_path, sec_findings=[])

    exit_code = execute_review(
        workspace_root=tmp_path,
        specification_id="spec-1",
        build_context="build a widget",
        herdr=herdr,
    )

    assert exit_code == EXIT_CONSENSUS
    store = JsonlEventStore(events_root(tmp_path))
    assert store.latest_of_type("spec-1", ConsensusReached) is not None
    assert "Consensus reached" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_execute_review_returns_exit_deadlock_and_records_consensus_deadlocked(
    tmp_path: Path, capsys: object
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    herdr = FakeHerdrClient()
    _respond_with(
        herdr,
        tmp_path,
        sec_findings=[
            {"target_section": "Auth", "severity": "blocking", "description": "sec objects"}
        ],
    )

    exit_code = execute_review(
        workspace_root=tmp_path,
        specification_id="spec-1",
        build_context="build a widget",
        herdr=herdr,
    )

    assert exit_code == EXIT_DEADLOCK
    store = JsonlEventStore(events_root(tmp_path))
    assert store.latest_of_type("spec-1", ConsensusDeadlocked) is not None
    assert "Deadlocked" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_execute_review_rejects_a_roster_with_no_reviewers_before_starting_any_agent(
    tmp_path: Path,
) -> None:
    (tmp_path / "roundtable.toml").write_text(
        """
        round_limit = 1

        [[roster.agents]]
        name = "dev"
        role = "developer"
        persona = "Write the code."
        kind = "claude"
        """
    )
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()

    exit_code = execute_review(
        workspace_root=tmp_path,
        specification_id="spec-1",
        build_context="build a widget",
        herdr=herdr,
    )

    assert exit_code == EXIT_ORCHESTRATION_FAILURE
    assert herdr.opened_panes == []


def test_execute_review_rejects_a_roster_with_duplicate_names_before_starting_any_agent(
    tmp_path: Path,
) -> None:
    (tmp_path / "roundtable.toml").write_text(
        """
        round_limit = 1

        [[roster.agents]]
        name = "dev"
        role = "developer"
        persona = "Write the code."
        kind = "claude"

        [[roster.agents]]
        name = "dev"
        role = "security reviewer"
        persona = "Look for vulnerabilities."
        kind = "claude"
        """
    )
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()

    exit_code = execute_review(
        workspace_root=tmp_path,
        specification_id="spec-1",
        build_context="build a widget",
        herdr=herdr,
    )

    assert exit_code == EXIT_ORCHESTRATION_FAILURE
    assert herdr.opened_panes == []


def test_execute_review_returns_exit_orchestration_failure_without_recording_an_outcome(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path)
    herdr = FakeHerdrClient()
    herdr.fail_split_after = 0

    exit_code = execute_review(
        workspace_root=tmp_path,
        specification_id="spec-1",
        build_context="build a widget",
        herdr=herdr,
    )

    assert exit_code == EXIT_ORCHESTRATION_FAILURE
    store = JsonlEventStore(events_root(tmp_path))
    assert store.latest_of_type("spec-1", ConsensusReached) is None
    assert store.latest_of_type("spec-1", ConsensusDeadlocked) is None
