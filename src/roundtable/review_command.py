"""Shared execution shell for the `review` command: config, store, herdr client, runner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import click
from pydantic import ValidationError

from roundtable.config import load_config
from roundtable.events import ArtifactDrafted, ConsensusReached
from roundtable.herdr import HerdrClient, HerdrClientProtocol
from roundtable.orchestration import Deadlocked, ReachedConsensus, ReviewRunner, RunnerError
from roundtable.store import EventStoreProtocol, SqliteEventStore
from roundtable.workspace import config_path, events_db_path

EXIT_CONSENSUS = 0
EXIT_ORCHESTRATION_FAILURE = 1
EXIT_DEADLOCK = 2

ReviewTarget = Literal["spec", "code"]

CODE_PHASE_SUFFIX = ":code"


def execute_review(
    *,
    workspace_root: Path,
    specification_id: str,
    build_context: str,
    confirm: Callable[[], bool] | None = None,
    herdr: HerdrClientProtocol | None = None,
    store: EventStoreProtocol | None = None,
) -> int:
    """Run a full review against `specification_id`, returning the process exit code.

    Loads the workspace's roster and round limit, wires a herdr client and
    event store (real ones by default), and drives a `ReviewRunner` to
    completion.

    Args:
        workspace_root: The workspace's root directory.
        specification_id: The specification id the review is keyed under.
        build_context: The build context handed to the developer's first draft.
        confirm: Optional callback asking a human whether to resume after a
            deadlock; declining (or omitting it) ends the run at that
            deadlock.
        herdr: The herdr client to drive agents through; a real subprocess
            client when omitted.
        store: The event store to record against; a real SQLite store at
            the workspace's event database path when omitted.

    Returns:
        0 if consensus was reached, 2 if the run ended in an unresolved
        deadlock, 1 if orchestration itself failed before either outcome.
    """
    try:
        config = load_config(config_path(workspace_root))
    except ValidationError as exc:
        click.echo(f"Invalid roster configuration: {exc}", err=True)
        return EXIT_ORCHESTRATION_FAILURE

    store = store if store is not None else SqliteEventStore(events_db_path(workspace_root))
    herdr = herdr if herdr is not None else HerdrClient()
    runner = ReviewRunner(
        herdr=herdr,
        store=store,
        workspace_root=workspace_root,
        specification_id=specification_id,
        roster=config.roster,
        round_limit=config.round_limit,
        report=lambda message: click.echo(message),
    )

    try:
        outcome = runner.run(build_context=build_context, confirm=confirm)
    except RunnerError as exc:
        click.echo(f"Review failed: {exc}", err=True)
        return EXIT_ORCHESTRATION_FAILURE

    if isinstance(outcome, ReachedConsensus):
        click.echo(f"Consensus reached (state {outcome.final_state_id}).")
        return EXIT_CONSENSUS
    if isinstance(outcome, Deadlocked):
        click.echo(f"Deadlocked on {outcome.target_section}.")
        return EXIT_DEADLOCK
    return EXIT_ORCHESTRATION_FAILURE


def _resolve_spec_build_context(description: str | None, context_file: Path | None) -> str | None:
    """Return the spec phase's build context, or `None` if neither source was given."""
    if description is not None:
        return description
    if context_file is not None:
        return context_file.read_text()
    return None


def _resolve_code_review_context(store: EventStoreProtocol, specification_id: str) -> str | None:
    """Return the code phase's build context from `specification_id`'s approved spec.

    Returns `None` if the spec phase has not reached consensus.

    Raises:
        RuntimeError: a `ConsensusReached` event references a draft version
            with no matching `ArtifactDrafted` event — an invariant violation,
            since every recorded consensus references a draft recorded
            earlier in the same run.
    """
    consensus = store.latest_of_type(specification_id, ConsensusReached)
    if consensus is None:
        return None
    draft = next(
        (
            event
            for event in reversed(store.replay(specification_id))
            if isinstance(event, ArtifactDrafted) and event.version_id == consensus.final_state_id
        ),
        None,
    )
    if draft is None:
        raise RuntimeError(
            f"No ArtifactDrafted event found for {specification_id!r} at commit "
            f"{consensus.final_state_id!r}, though its ConsensusReached event references it."
        )
    return (
        f"Implement the specification approved at commit {consensus.final_state_id}:"
        f"\n\n{draft.content}"
    )


def run_review(
    *,
    workspace_root: Path,
    target: ReviewTarget,
    specification_id: str,
    description: str | None = None,
    context_file: Path | None = None,
    confirm: Callable[[], bool] | None = None,
    herdr: HerdrClientProtocol | None = None,
    store: EventStoreProtocol | None = None,
) -> int:
    """Dispatch `review` to its spec or code phase, resolving each target's build context.

    The spec phase is keyed under `specification_id` directly; the code
    phase is keyed under the derived id `f"{specification_id}:code"`, so
    their event histories and Git state replay independently.

    Args:
        workspace_root: The workspace's root directory.
        target: `"spec"` to draft/revise the OpenSpec change, or `"code"` to
            draft/revise its implementation from the spec phase's approved state.
        specification_id: The specification id the spec phase is keyed under.
        description: An inline description of what to build, for `target="spec"`.
        context_file: A file whose content describes what to build, for
            `target="spec"`, used when `description` is not given.
        confirm: Optional callback asking a human whether to resume after a deadlock.
        herdr: The herdr client to drive agents through; a real subprocess
            client when omitted.
        store: The event store to record against; a real SQLite store at
            the workspace's event database path when omitted.

    Returns:
        0 if consensus was reached, 2 if the run ended in an unresolved
        deadlock, 1 if orchestration failed or the target's prerequisites
        (build context for `spec`, prior consensus for `code`) were not met
        — in which case no agent turn is started.
    """
    store = store if store is not None else SqliteEventStore(events_db_path(workspace_root))

    if target == "spec":
        build_context = _resolve_spec_build_context(description, context_file)
        if build_context is None:
            click.echo(
                "A description of what to build is required: pass --description or --context-file.",
                err=True,
            )
            return EXIT_ORCHESTRATION_FAILURE
        effective_id = specification_id
    else:
        build_context = _resolve_code_review_context(store, specification_id)
        if build_context is None:
            click.echo(
                f"Spec review for {specification_id!r} has not reached consensus; "
                "run `review spec` first.",
                err=True,
            )
            return EXIT_ORCHESTRATION_FAILURE
        effective_id = f"{specification_id}{CODE_PHASE_SUFFIX}"

    return execute_review(
        workspace_root=workspace_root,
        specification_id=effective_id,
        build_context=build_context,
        confirm=confirm,
        herdr=herdr,
        store=store,
    )
