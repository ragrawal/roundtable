"""Step definitions exercising `roundtable.orchestration.ReviewRunner` via a fake herdr client."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from pytest_bdd import given, parsers, then, when

from roundtable.config import AgentProfile, AgentRoster
from roundtable.orchestration import (
    Deadlocked,
    IncompleteRoundError,
    PaneAllocationError,
    ReviewRunner,
    RoundOutcome,
    RunnerError,
)
from tests.unit.test_review_runner import FakeEventStore, FakeHerdrClient, _init_git_repo

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)
PM_REVIEWER = AgentProfile(name="pm", role="product manager", persona="Check scope.", kind="claude")
ROSTER = AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER, PM_REVIEWER])


@dataclass
class OrchestrationContext:
    root: Path
    herdr: FakeHerdrClient
    store: FakeEventStore
    runner: ReviewRunner
    skip_result_for: set[str] = field(default_factory=set)
    blocking_for: dict[str, str] = field(default_factory=dict)
    outcome: RoundOutcome | None = None
    error: Exception | None = None
    messages: list[str] = field(default_factory=list)


def _wire_responses(context: OrchestrationContext) -> None:
    call_counts = {"dev": 0, "sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        del text
        agent = next(name for name, pane in context.herdr.started_agents.items() if pane == target)
        call_counts[agent] += 1
        if agent in context.skip_result_for:
            return
        result_path = (
            context.root / ".roundtable" / "scratch" / str(call_counts[agent]) / f"{agent}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            result_path.write_text(json.dumps({"summary": "the draft"}))
        elif agent in context.blocking_for:
            section = context.blocking_for[agent]
            result_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "target_section": section,
                                "severity": "blocking",
                                "description": f"{section} needs work",
                            }
                        ]
                    }
                )
            )
        else:
            result_path.write_text(json.dumps({"findings": []}))

    context.herdr.respond = respond


@given("a roster of one developer and two reviewers", target_fixture="orchestration_context")
def given_roster(tmp_path: Path) -> OrchestrationContext:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    messages: list[str] = []
    runner = ReviewRunner(
        herdr=herdr,
        store=store,
        workspace_root=tmp_path,
        specification_id="spec-1",
        roster=ROSTER,
        round_limit=1,
        report=messages.append,
    )
    context = OrchestrationContext(
        root=tmp_path, herdr=herdr, store=store, runner=runner, messages=messages
    )
    _wire_responses(context)
    return context


@given(parsers.parse('the "{agent_name}" agent\'s pane cannot be allocated'))
def given_pane_allocation_fails(
    orchestration_context: OrchestrationContext, agent_name: str
) -> None:
    index = next(i for i, agent in enumerate(ROSTER.agents) if agent.name == agent_name)
    orchestration_context.herdr.fail_split_after = index


@given(parsers.parse('the "{agent_name}" reviewer never writes a critique result'))
def given_reviewer_never_writes_result(
    orchestration_context: OrchestrationContext, agent_name: str
) -> None:
    orchestration_context.skip_result_for.add(agent_name)


@given(parsers.parse('the "{agent_name}" reviewer blocks on "{section}"'))
def given_reviewer_blocks(
    orchestration_context: OrchestrationContext, agent_name: str, section: str
) -> None:
    orchestration_context.blocking_for[agent_name] = section


@given(
    parsers.parse(
        'the "{waiting_agent}" reviewer waits for the "{finishing_agent}" reviewer to finish first'
    )
)
def given_reviewer_waits_for_another(
    orchestration_context: OrchestrationContext, waiting_agent: str, finishing_agent: str
) -> None:
    finished = threading.Event()
    base_respond = orchestration_context.herdr.respond
    assert base_respond is not None

    def respond(target: str, text: str) -> None:
        agent = next(
            name
            for name, pane in orchestration_context.herdr.started_agents.items()
            if pane == target
        )
        if agent == waiting_agent:
            finished.wait(timeout=5)
        base_respond(target, text)
        if agent == finishing_agent:
            finished.set()

    orchestration_context.herdr.respond = respond


@when(parsers.parse('a review run starts with build context "{build_context}"'))
def when_review_run_starts(orchestration_context: OrchestrationContext, build_context: str) -> None:
    try:
        outcome = orchestration_context.runner.run(build_context=build_context)
    except RunnerError as exc:
        orchestration_context.error = exc
        return
    orchestration_context.outcome = outcome


@then("three panes are allocated, one per agent")
def then_three_panes_allocated(orchestration_context: OrchestrationContext) -> None:
    assert set(orchestration_context.herdr.started_agents) == {"dev", "sec", "pm"}
    assert len(orchestration_context.herdr.opened_panes) == 3


@then(parsers.parse('the run fails reporting that the "{agent_name}" agent could not be placed'))
def then_run_fails_reporting_agent(
    orchestration_context: OrchestrationContext, agent_name: str
) -> None:
    assert isinstance(orchestration_context.error, PaneAllocationError)
    assert orchestration_context.error.agent_name == agent_name


@then("the panes already allocated for the run are torn down")
def then_panes_torn_down(orchestration_context: OrchestrationContext) -> None:
    assert orchestration_context.herdr.closed_panes == orchestration_context.herdr.opened_panes


@then(parsers.parse('the run reports the round as incomplete, naming "{agent_name}"'))
def then_run_reports_incomplete(
    orchestration_context: OrchestrationContext, agent_name: str
) -> None:
    assert isinstance(orchestration_context.error, IncompleteRoundError)
    assert agent_name in orchestration_context.error.failed_reviewers


@then(parsers.parse('the run declares a deadlock on "{section}"'))
def then_run_declares_deadlock(orchestration_context: OrchestrationContext, section: str) -> None:
    assert isinstance(orchestration_context.outcome, Deadlocked)
    assert orchestration_context.outcome.target_section == section


@then(parsers.parse('the "{agent_name}" agent\'s pane remains open for escalation'))
def then_pane_remains_open(orchestration_context: OrchestrationContext, agent_name: str) -> None:
    pane_id = orchestration_context.herdr.started_agents[agent_name]
    assert pane_id not in orchestration_context.herdr.closed_panes
    assert agent_name in orchestration_context.runner.panes


@then(
    parsers.parse(
        'the "{first_agent}" reviewer\'s result is reported before the "{second_agent}" '
        "reviewer's result"
    )
)
def then_reviewer_reported_before(
    orchestration_context: OrchestrationContext, first_agent: str, second_agent: str
) -> None:
    def index_of_result(agent_name: str) -> int:
        return next(
            i
            for i, message in enumerate(orchestration_context.messages)
            if message.startswith(f"{agent_name} raised")
            or message.startswith(f"{agent_name}'s turn")
        )

    assert index_of_result(first_agent) < index_of_result(second_agent)


@then(parsers.parse("round {round_number:d}'s scratch artifacts remain on disk"))
def then_scratch_artifacts_remain(
    orchestration_context: OrchestrationContext, round_number: int
) -> None:
    scratch_dir = orchestration_context.root / ".roundtable" / "scratch" / str(round_number)
    assert scratch_dir.is_dir()
    assert any(scratch_dir.iterdir())
