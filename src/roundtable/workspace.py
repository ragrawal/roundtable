"""Workspace creation: prerequisite checks, Git/OpenSpec scaffolding, and `roundtable.toml` I/O."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import tomli_w

from roundtable.config import RoundtableConfig
from roundtable.herdr import HerdrClient, HerdrNotFoundError, UnsupportedHerdrVersionError

CONFIG_FILENAME = "roundtable.toml"
ROUNDTABLE_DIR = ".roundtable"
SCRATCH_DIRNAME = "scratch"
EVENTS_DIRNAME = "events"
SCRATCH_GITIGNORE_ENTRY = f"{ROUNDTABLE_DIR}/{SCRATCH_DIRNAME}/"


class PrerequisiteError(Exception):
    """Raised when an external prerequisite (`git`, a supported `herdr`) is unavailable."""

    def __init__(self, prerequisite: str, message: str) -> None:
        """Record which prerequisite failed.

        Args:
            prerequisite: Name of the missing or unsupported prerequisite, e.g. `"git"`.
            message: Human-readable detail of what's wrong.
        """
        self.prerequisite = prerequisite
        super().__init__(message)


class WorkspaceConflictError(Exception):
    """Raised when `init` targets a directory that already has a roundtable workspace."""

    def __init__(self, path: Path) -> None:
        """Record the conflicting config file's path.

        Args:
            path: Path to the existing `roundtable.toml`.
        """
        self.path = path
        super().__init__(
            f"A roundtable workspace already exists at {path}; pass --reinit to replace it."
        )


def check_conflict(workspace_root: Path, *, reinit: bool) -> None:
    """Raise `WorkspaceConflictError` if a workspace already exists and `reinit` wasn't asked for.

    Args:
        workspace_root: Directory `init` is targeting.
        reinit: Whether the caller explicitly requested reinitialization.
    """
    path = config_path(workspace_root)
    if path.exists() and not reinit:
        raise WorkspaceConflictError(path)


def check_prerequisites(herdr: HerdrClient) -> None:
    """Verify `git` and a supported `herdr` are available, before any filesystem write.

    Args:
        herdr: The client to detect and validate herdr's version through.

    Raises:
        PrerequisiteError: `git` is not on `PATH`, or the installed `herdr` is
            missing or an unsupported version.
    """
    if shutil.which("git") is None:
        raise PrerequisiteError("git", "The 'git' executable was not found on PATH.")
    try:
        herdr.assert_supported_version()
    except (HerdrNotFoundError, UnsupportedHerdrVersionError) as exc:
        raise PrerequisiteError("herdr", str(exc)) from exc


def config_path(workspace_root: Path) -> Path:
    """Path to `workspace_root`'s `roundtable.toml`."""
    return workspace_root / CONFIG_FILENAME


def events_root(workspace_root: Path) -> Path:
    """Path to `workspace_root`'s event store directory."""
    return workspace_root / ROUNDTABLE_DIR / EVENTS_DIRNAME


def scratch_root(workspace_root: Path) -> Path:
    """Path to `workspace_root`'s gitignored round-scratch directory."""
    return workspace_root / ROUNDTABLE_DIR / SCRATCH_DIRNAME


def write_config(workspace_root: Path, config: RoundtableConfig) -> Path:
    """Write `config` to `workspace_root`'s `roundtable.toml`, returning its path."""
    path = config_path(workspace_root)
    path.write_text(tomli_w.dumps(config.model_dump(mode="json")))
    return path


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603, S607
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )


def _is_inside_git_repo(path: Path) -> bool:
    return _run_git("rev-parse", "--is-inside-work-tree", cwd=path).returncode == 0


def _ensure_gitignore(workspace_root: Path) -> None:
    gitignore = workspace_root / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    if SCRATCH_GITIGNORE_ENTRY in existing_lines:
        return
    with gitignore.open("a") as handle:
        if existing_lines:
            handle.write("\n")
        handle.write(f"{SCRATCH_GITIGNORE_ENTRY}\n")


def _ensure_openspec_layout(workspace_root: Path) -> None:
    if (workspace_root / "openspec").exists():
        return
    subprocess.run(  # noqa: S603, S607
        ["openspec", "init", str(workspace_root), "--tools", "none", "--no-animation"],
        check=True,
        capture_output=True,
        text=True,
    )


def create_workspace(workspace_root: Path, config: RoundtableConfig) -> bool:
    """Create or reinitialize a review workspace at `workspace_root`.

    Creates the OpenSpec project layout, an event store directory, a
    gitignored round-scratch directory, and the roster/round-limit config
    file. Reuses an existing Git repository if `workspace_root` is already
    inside one; otherwise initializes one and makes an initial commit of the
    freshly created scaffold.

    Args:
        workspace_root: Directory to create or reinitialize the workspace in.
        config: The roster and round limit to write.

    Returns:
        Whether a new Git repository was initialized (`False` if an existing
        repository was reused).
    """
    workspace_root.mkdir(parents=True, exist_ok=True)
    reused_git = _is_inside_git_repo(workspace_root)
    if not reused_git:
        _run_git("init", cwd=workspace_root)

    _ensure_openspec_layout(workspace_root)
    events_root(workspace_root).mkdir(parents=True, exist_ok=True)
    scratch_root(workspace_root).mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(workspace_root)
    write_config(workspace_root, config)

    if not reused_git:
        _run_git("add", "-A", cwd=workspace_root)
        _run_git("commit", "-m", "Initialize roundtable workspace", cwd=workspace_root)
    return not reused_git
