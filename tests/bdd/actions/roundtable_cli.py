"""Step definitions for exercising the `roundtable init` CLI as an end-to-end subprocess.

A fake `herdr` executable stands in for the real herdr CLI, which is not
installed in the test environment, so `init`'s prerequisite check can be
satisfied end-to-end without a live herdr install.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_bdd import given, parsers

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.workspace import create_workspace

FAKE_HERDR_SCRIPT = "#!/bin/sh\necho 'herdr 0.9.1'\n"

ROSTER_CONFIG_TEMPLATE = """
round_limit = {round_limit}

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


@given("herdr is available")
def given_herdr_is_available(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path_factory.mktemp("fake-herdr-bin")
    herdr_path = bin_dir / "herdr"
    herdr_path.write_text(FAKE_HERDR_SCRIPT)
    herdr_path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@given("herdr is not installed")
def given_herdr_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    directories = os.environ.get("PATH", "").split(os.pathsep)
    without_herdr = [d for d in directories if not (Path(d) / "herdr").exists()]
    monkeypatch.setenv("PATH", os.pathsep.join(without_herdr))


@given(
    parsers.parse(
        'a roster config file "{filename}" with a developer and a security reviewer '
        "and a round limit of {round_limit:d}"
    )
)
def given_roster_config_file(filename: str, round_limit: int, tmp_dir: Path) -> None:
    (tmp_dir / filename).write_text(ROSTER_CONFIG_TEMPLATE.format(round_limit=round_limit))


@given("a roundtable workspace is already initialized there")
def given_workspace_already_initialized(tmp_dir: Path) -> None:
    config = RoundtableConfig(
        roster=AgentRoster(
            agents=[
                AgentProfile(
                    name="dev", role="developer", persona="Write the code.", kind="claude"
                ),
                AgentProfile(
                    name="sec",
                    role="security reviewer",
                    persona="Look for vulnerabilities.",
                    kind="claude",
                ),
            ]
        ),
        round_limit=2,
    )
    create_workspace(tmp_dir, config)
