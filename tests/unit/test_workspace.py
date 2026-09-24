"""Unit tests for roundtable.workspace: prerequisites, conflict checks, and scaffolding."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.herdr import HerdrClient, UnsupportedHerdrVersionError
from roundtable.workspace import (
    PrerequisiteError,
    WorkspaceConflictError,
    check_conflict,
    check_prerequisites,
    config_path,
    create_workspace,
    events_root,
    scratch_root,
    write_config,
)

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)
PM_REVIEWER = AgentProfile(name="pm", role="product manager", persona="Check scope.", kind="claude")
CONFIG = RoundtableConfig(
    roster=AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER, PM_REVIEWER]), round_limit=3
)


class _UnsupportedHerdrClient(HerdrClient):
    def assert_supported_version(self) -> None:
        raise UnsupportedHerdrVersionError("2.0.0", 0)


def test_check_prerequisites_raises_when_herdr_is_not_on_path() -> None:
    herdr = HerdrClient(binary="totally-nonexistent-herdr-binary-xyz")
    with pytest.raises(PrerequisiteError, match="herdr") as excinfo:
        check_prerequisites(herdr)
    assert excinfo.value.prerequisite == "herdr"


def test_check_prerequisites_raises_when_herdr_version_is_unsupported() -> None:
    with pytest.raises(PrerequisiteError, match="not supported") as excinfo:
        check_prerequisites(_UnsupportedHerdrClient())
    assert excinfo.value.prerequisite == "herdr"


def test_check_prerequisites_makes_no_filesystem_changes(tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    with pytest.raises(PrerequisiteError):
        check_prerequisites(HerdrClient(binary="totally-nonexistent-herdr-binary-xyz"))
    assert set(tmp_path.iterdir()) == before


def test_check_conflict_passes_when_no_existing_config(tmp_path: Path) -> None:
    check_conflict(tmp_path, reinit=False)


def test_check_conflict_raises_naming_the_conflicting_path(tmp_path: Path) -> None:
    write_config(tmp_path, CONFIG)
    with pytest.raises(WorkspaceConflictError) as excinfo:
        check_conflict(tmp_path, reinit=False)
    assert excinfo.value.path == config_path(tmp_path)
    assert str(config_path(tmp_path)) in str(excinfo.value)


def test_check_conflict_passes_with_reinit_even_if_config_exists(tmp_path: Path) -> None:
    write_config(tmp_path, CONFIG)
    check_conflict(tmp_path, reinit=True)


def test_create_workspace_creates_every_component_in_an_empty_directory(tmp_path: Path) -> None:
    created_new_git = create_workspace(tmp_path, CONFIG)

    assert created_new_git is True
    assert (tmp_path / "openspec" / "config.yaml").exists()
    assert (tmp_path / ".git").is_dir()
    assert events_root(tmp_path).is_dir()
    assert scratch_root(tmp_path).is_dir()
    assert config_path(tmp_path).exists()
    gitignore_text = (tmp_path / ".gitignore").read_text()
    assert ".roundtable/scratch/" in gitignore_text

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert log.stdout.strip() != ""


def test_create_workspace_reuses_an_existing_git_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=True)
    (tmp_path / "pre-existing.txt").write_text("keep me\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "pre-existing history"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    log_before = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout

    created_new_git = create_workspace(tmp_path, CONFIG)

    assert created_new_git is False
    log_after = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    assert log_after == log_before
    assert (tmp_path / "pre-existing.txt").read_text() == "keep me\n"
    assert config_path(tmp_path).exists()


def test_create_workspace_reinit_replaces_roster_but_preserves_event_store(tmp_path: Path) -> None:
    create_workspace(tmp_path, CONFIG)
    events_root(tmp_path).joinpath("events.db").write_text("kept")

    replacement = RoundtableConfig(
        roster=AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER]), round_limit=5
    )
    create_workspace(tmp_path, replacement)

    from roundtable.config import load_config

    assert load_config(config_path(tmp_path)).round_limit == 5
    assert events_root(tmp_path).joinpath("events.db").read_text() == "kept"
