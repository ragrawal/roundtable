"""Unit tests for roundtable.config: AgentRoster validation and TOML loading."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from roundtable.config import (
    DEFAULT_ROUND_LIMIT,
    MINIMUM_ROUND_LIMIT,
    AgentProfile,
    AgentRoster,
    RoundtableConfig,
    load_config,
)

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)
PM_REVIEWER = AgentProfile(name="pm", role="product manager", persona="Check scope.", kind="codex")


def test_roster_with_one_developer_and_reviewers_is_valid() -> None:
    roster = AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER, PM_REVIEWER])

    assert roster.developer.name == "dev"
    assert {r.name for r in roster.reviewers} == {"sec", "pm"}


def test_roster_missing_developer_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one developer"):
        AgentRoster(agents=[SECURITY_REVIEWER, PM_REVIEWER])


def test_roster_with_two_developers_is_rejected() -> None:
    second_developer = DEVELOPER.model_copy(update={"name": "dev-2"})
    with pytest.raises(ValidationError, match="exactly one developer"):
        AgentRoster(agents=[DEVELOPER, second_developer, SECURITY_REVIEWER])


def test_roster_with_no_reviewers_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one reviewer"):
        AgentRoster(agents=[DEVELOPER])


def test_roster_with_duplicate_names_is_rejected() -> None:
    duplicate = SECURITY_REVIEWER.model_copy(update={"name": "dev"})
    with pytest.raises(ValidationError, match="Agent names must be unique") as excinfo:
        AgentRoster(agents=[DEVELOPER, duplicate])
    assert "dev" in str(excinfo.value)


def test_agent_profile_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        AgentProfile.model_validate({**DEVELOPER.model_dump(), "extra_field": "surprise"})


@pytest.mark.parametrize("name", ["senior engineer", "Dev", "-dev", "a" * 33, "dev!", ""], ids=repr)
def test_agent_profile_rejects_a_name_that_violates_herdrs_naming_rule(name: str) -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        AgentProfile(name=name, role="developer", persona="Write the code.", kind="claude")


def test_agent_profile_accepts_a_name_at_herdrs_length_limit() -> None:
    name = "a" * 32
    agent = AgentProfile(name=name, role="developer", persona="Write the code.", kind="claude")
    assert agent.name == name


def _write_toml(path: Path, text: str) -> Path:
    config_path = path / "roundtable.toml"
    config_path.write_text(text)
    return config_path


def _valid_toml_text() -> str:
    return """
round_limit = 4

[[roster.agents]]
name = "dev"
role = "developer"
persona = "Write the code."
kind = "claude"

[[roster.agents]]
name = "sec"
role = "security reviewer"
persona = "Look for vulnerabilities."
kind = "claude"
"""


def test_load_config_reads_a_valid_file(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, _valid_toml_text())

    config = load_config(path)

    assert isinstance(config, RoundtableConfig)
    assert config.round_limit == 4
    assert config.roster.developer.name == "dev"
    assert [r.name for r in config.roster.reviewers] == ["sec"]


def test_load_config_uses_default_round_limit_when_absent(tmp_path: Path) -> None:
    text = _valid_toml_text().replace("round_limit = 4\n", "")
    path = _write_toml(tmp_path, text)

    config = load_config(path)

    assert config.round_limit == DEFAULT_ROUND_LIMIT


def test_load_config_rejects_round_limit_below_minimum(tmp_path: Path) -> None:
    text = _valid_toml_text().replace("round_limit = 4", "round_limit = 0")
    path = _write_toml(tmp_path, text)

    with pytest.raises(ValidationError, match="round_limit"):
        load_config(path)
    assert MINIMUM_ROUND_LIMIT == 1


def test_load_config_rejects_malformed_toml(tmp_path: Path) -> None:
    path = _write_toml(tmp_path, "not [ valid toml")

    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(path)
