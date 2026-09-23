"""Workspace configuration: agent roster and round-limit models, TOML loading."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

DEVELOPER_ROLE = "developer"

DEFAULT_ROUND_LIMIT = 3
MINIMUM_ROUND_LIMIT = 1

AGENT_NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"
"""herdr's own agent-name rule: a lowercase letter, then up to 31 lowercase
letters, digits, `-`, or `_`. An agent whose name violates this is accepted
by `AgentProfile` but rejected by herdr only once a review is already
running, deep inside pane allocation — validating it here instead lets
`roundtable init` catch it immediately."""


class AgentProfile(BaseModel):
    """One agent's configuration: its identity, role, focus, and the LLM that runs it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        pattern=AGENT_NAME_PATTERN,
        description="Workspace-unique name identifying this agent; must start with a "
        "lowercase letter and contain only lowercase letters, digits, '-', or '_' "
        "(max 32 characters), per herdr's agent-naming rule.",
    )
    role: str = Field(
        ..., description="This agent's role, e.g. 'developer' or 'security reviewer'."
    )
    persona: str = Field(
        ...,
        description="Focus prompt for what this agent should pay attention to when reviewing.",
    )
    kind: str = Field(..., description="The LLM that runs this agent, e.g. 'claude' or 'codex'.")

    @property
    def is_developer(self) -> bool:
        """Whether this agent's role is the developer role."""
        return self.role == DEVELOPER_ROLE


class AgentRoster(BaseModel):
    """The agents participating in a review: exactly one developer, one or more reviewers."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentProfile] = Field(..., description="Every agent participating in the review.")

    @model_validator(mode="after")
    def _validate_roster(self) -> AgentRoster:
        developers = [agent for agent in self.agents if agent.is_developer]
        if not developers:
            raise ValueError("Roster must include exactly one developer agent; none was found.")
        if len(developers) > 1:
            names = ", ".join(agent.name for agent in developers)
            raise ValueError(
                f"Roster must include exactly one developer agent; "
                f"found {len(developers)}: {names}."
            )
        if len(self.agents) == len(developers):
            raise ValueError("Roster must include at least one reviewer agent; none was found.")
        names = [agent.name for agent in self.agents]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Agent names must be unique; duplicated: {', '.join(duplicates)}.")
        return self

    @property
    def developer(self) -> AgentProfile:
        """The roster's single developer agent."""
        return next(agent for agent in self.agents if agent.is_developer)

    @property
    def reviewers(self) -> list[AgentProfile]:
        """Every reviewer agent in the roster, in configured order."""
        return [agent for agent in self.agents if not agent.is_developer]


class RoundtableConfig(BaseSettings):
    """A workspace's full configuration: its agent roster and review round limit."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(extra="forbid")

    roster: AgentRoster = Field(..., description="The workspace's agent roster.")
    round_limit: int = Field(
        default=DEFAULT_ROUND_LIMIT,
        ge=MINIMUM_ROUND_LIMIT,
        description="Maximum number of automatic revision rounds before declaring a deadlock.",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Restrict configuration to explicitly supplied values: no env or dotenv sources."""
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def load_config(path: Path) -> RoundtableConfig:
    """Load and validate a `RoundtableConfig` from a `roundtable.toml`-shaped file.

    Args:
        path: Path to the TOML configuration file.

    Returns:
        The parsed and validated configuration.

    Raises:
        tomllib.TOMLDecodeError: `path`'s contents are not valid TOML.
        pydantic.ValidationError: the parsed data fails roster or round-limit validation.
    """
    toml_source = TomlConfigSettingsSource(RoundtableConfig, toml_file=path)
    return RoundtableConfig(**toml_source())
