"""Step definitions driving `roundtable review` in-process against a fake herdr client.

No real herdr server is available in tests, so these steps call
`roundtable.review_command.run_review` directly, scripting a `FakeHerdrClient`
to stand in for the developer and security-reviewer agents, rather than
shelling out to a `roundtable` subprocess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pytest_bdd import given, parsers, then, when

from roundtable.config import AgentProfile, AgentRoster, RoundtableConfig
from roundtable.events import ArtifactDrafted, ConsensusDeadlocked, ConsensusReached
from roundtable.review_command import EXIT_CONSENSUS, EXIT_DEADLOCK, run_review
from roundtable.workspace import write_config
from tests.unit.test_review_runner import FakeEventStore, FakeHerdrClient, _init_git_repo

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)


@dataclass
class ReviewWorkspace:
    """Accumulated state for a scenario's scripted, multi-invocation review run."""

    root: Path
    store: FakeEventStore
    sec_findings_by_round: dict[int, list[dict[str, str]]] = field(default_factory=dict)
    exit_code: int | None = None


def _new_scripted_herdr(workspace: ReviewWorkspace) -> FakeHerdrClient:
    """A fresh `FakeHerdrClient` whose developer always drafts and whose reviewer
    raises `workspace.sec_findings_by_round`'s findings, keyed by its own turn count."""
    herdr = FakeHerdrClient()
    call_counts = {"dev": 0, "sec": 0}

    def respond(target: str, text: str) -> None:
        del text
        agent = next(name for name, pane in herdr.started_agents.items() if pane == target)
        call_counts[agent] += 1
        result_path = (
            workspace.root / ".roundtable" / "scratch" / str(call_counts[agent]) / f"{agent}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            result_path.write_text(json.dumps({"summary": f"draft {call_counts[agent]}"}))
        else:
            findings = workspace.sec_findings_by_round.get(call_counts[agent], [])
            result_path.write_text(json.dumps({"findings": findings}))

    herdr.respond = respond
    return herdr


@given(
    parsers.parse(
        "a roundtable workspace with a developer and a security reviewer "
        "and a round limit of {round_limit:d}"
    ),
    target_fixture="review_workspace",
)
def given_workspace(tmp_path: Path, round_limit: int) -> ReviewWorkspace:
    config = RoundtableConfig(
        roster=AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER]), round_limit=round_limit
    )
    write_config(tmp_path, config)
    _init_git_repo(tmp_path)
    return ReviewWorkspace(root=tmp_path, store=FakeEventStore())


@given(parsers.parse('the security reviewer blocks on "{section}" in round {round_number:d}'))
def given_reviewer_blocks(
    review_workspace: ReviewWorkspace, section: str, round_number: int
) -> None:
    review_workspace.sec_findings_by_round[round_number] = [
        {"target_section": section, "severity": "blocking", "description": f"{section} needs work"}
    ]


@when(
    parsers.parse(
        'roundtable review spec "{specification_id}" is run with description "{description}"'
    )
)
def when_review_spec_is_run(
    review_workspace: ReviewWorkspace, specification_id: str, description: str
) -> None:
    review_workspace.exit_code = run_review(
        workspace_root=review_workspace.root,
        target="spec",
        specification_id=specification_id,
        description=description,
        herdr=_new_scripted_herdr(review_workspace),
        store=review_workspace.store,
    )


@when(parsers.parse('roundtable review code "{specification_id}" is run'))
def when_review_code_is_run(review_workspace: ReviewWorkspace, specification_id: str) -> None:
    review_workspace.exit_code = run_review(
        workspace_root=review_workspace.root,
        target="code",
        specification_id=specification_id,
        herdr=_new_scripted_herdr(review_workspace),
        store=review_workspace.store,
    )


@then("the review reaches consensus")
def then_reaches_consensus(review_workspace: ReviewWorkspace) -> None:
    assert review_workspace.exit_code == EXIT_CONSENSUS


@then(parsers.parse('the review deadlocks on "{section}"'))
def then_deadlocks(review_workspace: ReviewWorkspace, section: str) -> None:
    assert review_workspace.exit_code == EXIT_DEADLOCK


@then(
    parsers.parse(
        'the event log for "{specification_id}" replays'
        " {draft_count:d} draft(s) ending in {outcome}"
    )
)
def then_event_log_replays(
    review_workspace: ReviewWorkspace, specification_id: str, draft_count: int, outcome: str
) -> None:
    events = review_workspace.store.replay(specification_id)
    drafts = [event for event in events if isinstance(event, ArtifactDrafted)]
    assert len(drafts) == draft_count
    if outcome == "consensus":
        assert isinstance(events[-1], ConsensusReached)
    elif outcome == "deadlock":
        assert isinstance(events[-1], ConsensusDeadlocked)
    else:
        raise ValueError(f"Unknown outcome {outcome!r}; expected 'consensus' or 'deadlock'.")


@then(parsers.parse('the event log for "{specification_id}" contains only its own events'))
def then_event_log_contains_only_its_own_events(
    review_workspace: ReviewWorkspace, specification_id: str
) -> None:
    events = review_workspace.store.replay(specification_id)
    assert events
    assert all(event.specification_id == specification_id for event in events)
