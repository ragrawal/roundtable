"""Roster read/write HTTP endpoints backed by `roundtable.toml`.

The write endpoint is the UI's one write path: it holds `roster_lock` across
the entire read-validate-write sequence (see `lock.py`), re-reads the
config so it never overwrites a concurrent change to fields it isn't
editing, and writes back atomically via temp-file-then-rename.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomli_w
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig, load_config
from roundtable.web.lock import RosterLockedError, roster_lock

LOCKED_STATUS_CODE = 409
VALIDATION_STATUS_CODE = 422


class RosterResponse(BaseModel):
    """The workspace's current roster and round limit, as shown by the editor."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentProfile] = Field(..., description="Every agent in the workspace's roster.")
    round_limit: int = Field(..., description="The workspace's configured maximum review rounds.")


class RosterSaveRequest(BaseModel):
    """A roster edit submitted for save."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentProfile] = Field(..., description="The full desired agent roster.")
    round_limit: int | None = Field(
        default=None,
        description="New round limit, or None to leave the workspace's current value unchanged.",
    )


def _config_to_response(config: RoundtableConfig) -> RosterResponse:
    return RosterResponse(agents=config.roster.agents, round_limit=config.round_limit)


def _write_config_atomically(path: Path, config: RoundtableConfig) -> None:
    """Serialize `config` to a temp file in `path`'s directory, then rename over `path`."""
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(tomli_w.dumps(config.model_dump(mode="json")))
    os.replace(tmp_path, path)


def build_roster_router(workspace_root: Path, config_path: Path) -> APIRouter:
    """Build the `/api/roster` router bound to one workspace.

    Args:
        workspace_root: The workspace the advisory lock is acquired in.
        config_path: Path to the workspace's `roundtable.toml`.

    Returns:
        A router exposing `GET`/`PUT` `/api/roster`.
    """
    router = APIRouter()

    @router.get("/api/roster", response_model=RosterResponse)
    def get_roster() -> RosterResponse:
        """Return the workspace's current roster and round limit."""
        return _config_to_response(load_config(config_path))

    @router.put("/api/roster", response_model=RosterResponse)
    def save_roster(edit: RosterSaveRequest) -> RosterResponse:
        """Validate and persist a roster edit, holding the advisory lock throughout."""
        try:
            with roster_lock(workspace_root):
                try:
                    current = load_config(config_path)
                except (ValidationError, tomllib.TOMLDecodeError, FileNotFoundError) as exc:
                    raise HTTPException(
                        status_code=VALIDATION_STATUS_CODE,
                        detail=f"Could not read the current roster: {exc}",
                    ) from exc

                try:
                    new_config = RoundtableConfig(
                        roster=AgentRoster(agents=edit.agents),
                        round_limit=(
                            edit.round_limit
                            if edit.round_limit is not None
                            else current.round_limit
                        ),
                    )
                except ValidationError as exc:
                    raise HTTPException(
                        status_code=VALIDATION_STATUS_CODE, detail=str(exc)
                    ) from exc

                _write_config_atomically(config_path, new_config)
                return _config_to_response(new_config)
        except RosterLockedError as exc:
            raise HTTPException(status_code=LOCKED_STATUS_CODE, detail=str(exc)) from exc

    return router
