"""Reusable shell-command step definitions shared across feature files."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pytest_bdd import given, parsers, then, when


@dataclass
class CommandResult:
    returncode: int
    output: str


def resolve(text: str, project_root: Path, tmp_dir: Path) -> str:
    return text.format(project_root=project_root, tmp_dir=tmp_dir)


def run_command(command: str, cwd: Path, project_root: Path, tmp_dir: Path) -> CommandResult:
    resolved = resolve(command, project_root, tmp_dir)
    result = subprocess.run(shlex.split(resolved), cwd=cwd, capture_output=True, text=True)
    return CommandResult(result.returncode, result.stdout + result.stderr)


@given("a temporary directory", target_fixture="tmp_dir")
def given_temporary_directory(tmp_path: Path) -> Path:
    return tmp_path


@when(parsers.parse('the user runs "{command}"'), target_fixture="last_result")
def when_user_runs(command: str, tmp_dir: Path, project_root: Path) -> CommandResult:
    return run_command(command, cwd=tmp_dir, project_root=project_root, tmp_dir=tmp_dir)


@when(parsers.parse('the user runs "{command}" in "{directory}"'), target_fixture="last_result")
def when_user_runs_in_directory(
    command: str, directory: str, tmp_dir: Path, project_root: Path
) -> CommandResult:
    cwd = Path(resolve(directory, project_root, tmp_dir))
    return run_command(command, cwd=cwd, project_root=project_root, tmp_dir=tmp_dir)


@then(parsers.parse("the command exits with code {code:d}"))
def then_command_exits_with_code(last_result: CommandResult, code: int) -> None:
    assert last_result.returncode == code, last_result.output


@then("the command exits with a non-zero code")
def then_command_exits_nonzero(last_result: CommandResult) -> None:
    assert last_result.returncode != 0, last_result.output


@then(parsers.parse('the output contains "{text}"'))
def then_output_contains(last_result: CommandResult, text: str) -> None:
    assert text.lower() in last_result.output.lower(), last_result.output
