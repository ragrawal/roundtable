"""Unit tests for roundtable.cli: the `init` command's prompt flow and side effects."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from roundtable import cli
from roundtable.config import load_config
from roundtable.herdr import HerdrClient, UnsupportedHerdrVersionError
from roundtable.workspace import config_path

runner = CliRunner()

# One blank line per prompt accepts its default; 1 (count) + 3 agents * 4 fields + 1 (round limit).
ACCEPT_ALL_DEFAULTS_INPUT = "\n" * (1 + 3 * 4 + 1)


def test_init_in_empty_directory_creates_workspace_with_default_roster(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    assert [(a.name, a.role, a.kind) for a in config.roster.agents] == [
        ("dev", "developer", "claude"),
        ("pm", "product manager", "claude"),
        ("sec", "security reviewer", "claude"),
    ]
    assert config.round_limit == 3
    assert str(tmp_path) in result.output
    assert "dev" in result.output and "pm" in result.output and "sec" in result.output


def test_init_configuring_a_roster_interactively(tmp_path: Path) -> None:
    answers = "\n".join(
        [
            "3",  # agent count
            "solo-dev",
            "developer",
            "Write the thing.",
            "codex",
            "qa",
            "qa engineer",
            "",  # accept the qa engineer's canned focus prompt
            "claude",
            "arch",
            "architecture reviewer",  # custom role
            "Check module boundaries.",
            "claude",
            "7",  # round limit
        ]
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=answers + "\n")

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    assert [(a.name, a.role, a.kind) for a in config.roster.agents] == [
        ("solo-dev", "developer", "codex"),
        ("qa", "qa engineer", "claude"),
        ("arch", "architecture reviewer", "claude"),
    ]
    assert config.round_limit == 7


def test_init_reprompts_agent_name_until_it_satisfies_herdrs_naming_rule(
    tmp_path: Path,
) -> None:
    answers = "\n".join(
        [
            "2",
            "senior engineer",  # invalid: contains a space
            "senior-engineer",  # valid
            "developer",
            "",
            "claude",
            "sec",
            "security reviewer",
            "",
            "claude",
            "3",
        ]
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=answers + "\n")

    assert result.exit_code == 0, result.output
    assert "must start with a lowercase letter" in result.output
    config = load_config(config_path(tmp_path))
    assert [a.name for a in config.roster.agents] == ["senior-engineer", "sec"]


def test_init_predefined_role_shows_its_default_focus_prompt_which_can_be_overridden(
    tmp_path: Path,
) -> None:
    answers = "\n".join(
        [
            "2",
            "dev",
            "developer",
            "",  # accept default developer focus prompt
            "claude",
            "sec",
            "security reviewer",
            "Actually just check for SQL injection.",  # override the default
            "claude",
            "3",
        ]
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=answers + "\n")

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    reviewer = next(a for a in config.roster.agents if a.name == "sec")
    assert reviewer.persona == "Actually just check for SQL injection."


def test_init_custom_role_requires_an_authored_focus_prompt(tmp_path: Path) -> None:
    answers = "\n".join(
        [
            "2",
            "dev",
            "developer",
            "",
            "claude",
            "reviewer",
            "chaos engineer",  # not on the predefined list
            "Break things under load.",  # required, no default offered
            "claude",
            "3",
        ]
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=answers + "\n")

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    reviewer = next(a for a in config.roster.agents if a.name == "reviewer")
    assert reviewer.role == "chaos engineer"
    assert reviewer.persona == "Break things under load."


def test_init_rejects_a_custom_kind_prompt_answer_by_accepting_it(tmp_path: Path) -> None:
    answers = "\n".join(
        [
            "2",
            "dev",
            "developer",
            "",
            "gemini",  # not on the predefined kind list
            "sec",
            "security reviewer",
            "",
            "claude",
            "3",
        ]
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=answers + "\n")

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    assert next(a for a in config.roster.agents if a.name == "dev").kind == "gemini"


def test_init_refuses_to_overwrite_an_existing_workspace(tmp_path: Path) -> None:
    runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)
    before = config_path(tmp_path).read_text()

    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)

    assert result.exit_code != 0
    assert str(config_path(tmp_path)) in result.output
    assert config_path(tmp_path).read_text() == before


def test_init_reinit_replaces_roster_and_preserves_the_event_store(tmp_path: Path) -> None:
    from roundtable.workspace import events_root

    runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)
    events_root(tmp_path).joinpath("some-spec.jsonl").write_text('{"kept": true}\n')

    replacement_input = (
        "\n".join(["2", "solo", "developer", "", "claude", "qa", "qa engineer", "", "claude", "3"])
        + "\n"
    )
    result = runner.invoke(cli.app, ["init", str(tmp_path), "--reinit"], input=replacement_input)

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    assert [a.name for a in config.roster.agents] == ["solo", "qa"]
    assert events_root(tmp_path).joinpath("some-spec.jsonl").read_text() == '{"kept": true}\n'


def test_init_reinit_prefills_the_previous_configuration(tmp_path: Path) -> None:
    runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)

    result = runner.invoke(
        cli.app, ["init", str(tmp_path), "--reinit"], input=ACCEPT_ALL_DEFAULTS_INPUT
    )

    assert result.exit_code == 0, result.output
    config = load_config(config_path(tmp_path))
    assert [(a.name, a.role, a.kind) for a in config.roster.agents] == [
        ("dev", "developer", "claude"),
        ("pm", "product manager", "claude"),
        ("sec", "security reviewer", "claude"),
    ]


def test_init_non_interactive_from_a_config_file(tmp_path: Path) -> None:
    config_file = tmp_path / "seed.toml"
    config_file.write_text(
        """
        round_limit = 4

        [[roster.agents]]
        name = "d"
        role = "developer"
        persona = "Write it."
        kind = "claude"

        [[roster.agents]]
        name = "r"
        role = "security reviewer"
        persona = "Review it."
        kind = "codex"
        """
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    result = runner.invoke(cli.app, ["init", str(workspace_dir), "--config", str(config_file)])

    assert result.exit_code == 0, result.output
    config = load_config(config_path(workspace_dir))
    assert config.round_limit == 4
    assert [a.name for a in config.roster.agents] == ["d", "r"]


def test_init_non_interactive_config_failing_roster_validation_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.toml"
    config_file.write_text(
        """
        [[roster.agents]]
        name = "only-dev"
        role = "developer"
        persona = "Write it."
        kind = "claude"
        """
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    result = runner.invoke(cli.app, ["init", str(workspace_dir), "--config", str(config_file)])

    assert result.exit_code != 0
    assert not config_path(workspace_dir).exists()


class _UnsupportedHerdrClient(HerdrClient):
    def assert_supported_version(self) -> None:
        raise UnsupportedHerdrVersionError("2.0.0", 0)


def test_init_fails_and_leaves_directory_untouched_when_herdr_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "HerdrClient", _UnsupportedHerdrClient)

    result = runner.invoke(cli.app, ["init", str(tmp_path)], input=ACCEPT_ALL_DEFAULTS_INPUT)

    assert result.exit_code != 0
    assert "herdr" in result.output
    assert list(tmp_path.iterdir()) == []
