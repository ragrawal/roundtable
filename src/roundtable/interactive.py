"""Interactive prompt flow for `roundtable init`: agent roster and round-limit collection."""

from __future__ import annotations

import re

import click

from roundtable.config import (
    AGENT_NAME_PATTERN,
    DEFAULT_ROUND_LIMIT,
    DEVELOPER_ROLE,
    AgentProfile,
    AgentRoster,
    RoundtableConfig,
)

_AGENT_NAME_RE = re.compile(AGENT_NAME_PATTERN)

PREDEFINED_ROLES: tuple[str, ...] = (
    DEVELOPER_ROLE,
    "product manager",
    "senior engineer",
    "security reviewer",
    "qa engineer",
)
"""Roles offered as a hint for the role prompt; a custom role may also be entered."""

PREDEFINED_KINDS: tuple[str, ...] = ("claude", "codex")
"""LLM kinds offered as a hint for the kind prompt; a custom kind may also be entered."""

ROLE_FOCUS_PROMPTS: dict[str, str] = {
    DEVELOPER_ROLE: "Write and revise the artifact under review based on incoming critique.",
    "product manager": "Check scope, requirements coverage, and user-facing consequences.",
    "senior engineer": "Review code quality, design soundness, and maintainability.",
    "security reviewer": "Look for vulnerabilities, unsafe defaults, and misuse of secrets.",
    "qa engineer": "Look for missing tests, edge cases, and regressions.",
}
"""Default focus prompt for each predefined role; custom roles have none."""

_SEED_NAMES: tuple[str, ...] = ("dev", "pm", "sec")
_SEED_ROLES: tuple[str, ...] = (DEVELOPER_ROLE, "product manager", "security reviewer")
_SEED_KIND = "claude"


def _default_agent_seed(index: int) -> AgentProfile:
    """The suggested agent for the 1-based `index` when no prior configuration exists."""
    if index <= len(_SEED_NAMES):
        name, role = _SEED_NAMES[index - 1], _SEED_ROLES[index - 1]
    else:
        name, role = f"agent-{index}", "security reviewer"
    return AgentProfile(name=name, role=role, persona=ROLE_FOCUS_PROMPTS[role], kind=_SEED_KIND)


def _prompt_choice_with_custom(label: str, choices: tuple[str, ...], default: str) -> str:
    """Prompt for `label`, showing `choices` as a hint but accepting any free-text answer."""
    hint = "/".join(choices)
    return click.prompt(f"{label} [{hint}]", default=default)


def _sanitize_agent_name(name: str) -> str:
    """Best-effort rewrite of `name` into herdr's allowed agent-name character set."""
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "agent"


def _prompt_agent_name(index: int, default_name: str) -> str:
    """Prompt for one agent's name, reprompting until it satisfies herdr's naming rule.

    If the offered default itself is invalid (e.g. carried over from a
    pre-existing config), the next prompt offers a sanitized suggestion
    instead of repeating the same invalid default forever.
    """
    while True:
        name = click.prompt(f"Agent {index} name", default=default_name)
        if _AGENT_NAME_RE.match(name):
            return name
        default_name = _sanitize_agent_name(name)
        click.echo(
            "Agent name must start with a lowercase letter and contain only "
            "lowercase letters, digits, '-', or '_' (max 32 characters); "
            f"{name!r} does not. Try something like {default_name!r}."
        )


def _prompt_agent(index: int, default: AgentProfile) -> AgentProfile:
    """Prompt for one agent's name, role, focus prompt, and kind."""
    name = _prompt_agent_name(index, default.name)
    role = _prompt_choice_with_custom(f"Agent {index} role", PREDEFINED_ROLES, default.role)

    persona_default = default.persona if role == default.role else ROLE_FOCUS_PROMPTS.get(role)
    if persona_default is not None:
        persona = click.prompt(f"Agent {index} focus prompt", default=persona_default)
    else:
        persona = click.prompt(f"Agent {index} focus prompt (no default for a custom role)")

    kind = _prompt_choice_with_custom(f"Agent {index} kind", PREDEFINED_KINDS, default.kind)
    return AgentProfile(name=name, role=role, persona=persona, kind=kind)


def prompt_config(existing: RoundtableConfig | None) -> RoundtableConfig:
    """Run the full interactive prompt sequence for a roster and round limit.

    Args:
        existing: A previously loaded configuration to pre-populate every
            prompt's default answer from, or `None` to use built-in
            suggestions (one developer plus a product manager and security
            reviewer, all `claude`, round limit 3).

    Returns:
        The roster and round limit entered by the user.
    """
    default_agents = existing.roster.agents if existing is not None else ()
    default_count = len(default_agents) if default_agents else len(_SEED_NAMES)
    count = click.prompt(
        "Number of agents (including the developer)", default=default_count, type=int
    )

    agents = [
        _prompt_agent(
            index,
            default_agents[index - 1]
            if index <= len(default_agents)
            else _default_agent_seed(index),
        )
        for index in range(1, count + 1)
    ]

    default_round_limit = existing.round_limit if existing is not None else DEFAULT_ROUND_LIMIT
    round_limit = click.prompt(
        "Maximum review rounds before declaring a deadlock", default=default_round_limit, type=int
    )
    return RoundtableConfig(roster=AgentRoster(agents=agents), round_limit=round_limit)
