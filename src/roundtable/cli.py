"""The `roundtable` command-line application: `init` and `review`."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import typer
from pydantic import ValidationError

from roundtable.config import RoundtableConfig, load_config
from roundtable.herdr import HerdrClient
from roundtable.interactive import prompt_config
from roundtable.review_command import ReviewTarget, run_review
from roundtable.workspace import (
    PrerequisiteError,
    WorkspaceConflictError,
    check_conflict,
    check_prerequisites,
    config_path,
    create_workspace,
)

app = typer.Typer(help="Multi-agent adversarial review for OpenSpec changes and their code.")


@app.callback()
def callback() -> None:
    """Multi-agent adversarial review for OpenSpec changes and their code."""


def _report_roster(workspace_root: Path, config: RoundtableConfig) -> None:
    typer.echo(f"Initialized roundtable workspace at {workspace_root}")
    roster_summary = ", ".join(
        f"{agent.name} ({agent.role}/{agent.kind})" for agent in config.roster.agents
    )
    typer.echo(f"Roster: {roster_summary}")
    typer.echo(f"Round limit: {config.round_limit}")


@app.command()
def init(
    path: Path = typer.Argument(
        Path("."), help="Directory to create or reinitialize the workspace in."
    ),
    reinit: bool = typer.Option(
        False, "--reinit", help="Replace an existing workspace's roster configuration."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Load the roster and round limit from a roundtable.toml-shaped file, "
        "skipping every prompt.",
    ),
) -> None:
    """Create or reinitialize a roundtable review workspace."""
    workspace_root = path.resolve()
    herdr = HerdrClient()

    try:
        check_prerequisites(herdr)
        check_conflict(workspace_root, reinit=reinit)
    except (PrerequisiteError, WorkspaceConflictError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    existing_path = config_path(workspace_root)
    existing = load_config(existing_path) if existing_path.exists() else None

    if config is not None:
        try:
            new_config = load_config(config)
        except (ValidationError, tomllib.TOMLDecodeError) as exc:
            typer.echo(f"Invalid config file {config}: {exc}", err=True)
            raise typer.Exit(1) from exc
    else:
        new_config = prompt_config(existing)

    create_workspace(workspace_root, new_config)
    _report_roster(workspace_root, new_config)


@app.command()
def review(
    target: str = typer.Argument(..., help="Review target: 'spec' or 'code'."),
    specification_id: str = typer.Argument(
        ..., help="Specification id the spec phase is keyed under."
    ),
    path: Path = typer.Option(Path("."), "--path", help="Workspace root directory."),
    description: str | None = typer.Option(
        None, "--description", help="Inline description of what to build ('spec' target only)."
    ),
    context_file: Path | None = typer.Option(
        None, "--context-file", help="File describing what to build ('spec' target only)."
    ),
) -> None:
    """Start a review round against a specification's OpenSpec change or its implementation."""
    if target not in ("spec", "code"):
        typer.echo(f"Unknown review target {target!r}; expected 'spec' or 'code'.", err=True)
        raise typer.Exit(1)

    exit_code = run_review(
        workspace_root=path.resolve(),
        target=cast(ReviewTarget, target),
        specification_id=specification_id,
        description=description,
        context_file=context_file,
        confirm=lambda: typer.confirm("Resume with a new round?"),
    )
    raise typer.Exit(exit_code)
