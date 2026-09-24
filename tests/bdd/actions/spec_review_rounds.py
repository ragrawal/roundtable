"""Step definitions for `ReviewRound`'s pure decision logic and the human-escalation
resume flow that starts a new critique round after a deadlock without re-drafting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pytest_bdd import given, parsers, then, when

from roundtable.config import AgentProfile, AgentRoster
from roundtable.events import CritiqueFinding, Severity
from roundtable.orchestration import (
    Deadlocked,
    IncompleteReviewerTurn,
    IncompleteRound,
    ReachedConsensus,
    RequestRevision,
    ReviewerTurn,
    ReviewRound,
    ReviewRunner,
    RoundOutcome,
)
from tests.unit.test_review_runner import FakeEventStore, FakeHerdrClient, _init_git_repo

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)


@dataclass
class DecisionContext:
    turns: list[ReviewerTurn | IncompleteReviewerTurn] = field(default_factory=list)
    outcome: RoundOutcome | None = None


@given("a draft awaiting critique", target_fixture="decision_context")
def given_draft_awaiting_critique() -> DecisionContext:
    return DecisionContext()


@given(parsers.parse('"{reviewer}" raises a "{severity}" critique on "{section}"'))
def given_reviewer_raises_critique(
    decision_context: DecisionContext, reviewer: str, severity: str, section: str
) -> None:
    finding = CritiqueFinding(
        target_section=section, severity=Severity(severity), description=f"{section} needs work"
    )
    decision_context.turns.append(ReviewerTurn(reviewer, (finding,)))


@given(parsers.parse('"{reviewer}" approves with no findings'))
def given_reviewer_approves(decision_context: DecisionContext, reviewer: str) -> None:
    decision_context.turns.append(ReviewerTurn(reviewer, ()))


@given(parsers.parse('"{reviewer}"\'s turn times out'))
def given_reviewer_times_out(decision_context: DecisionContext, reviewer: str) -> None:
    decision_context.turns.append(IncompleteReviewerTurn(reviewer, reason="timeout"))


@when(parsers.parse("the round is decided as round {round_number:d} of {round_limit:d}"))
def when_round_is_decided(
    decision_context: DecisionContext, round_number: int, round_limit: int
) -> None:
    decision_context.outcome = ReviewRound.decide(
        draft_version="sha-1",
        turns=tuple(decision_context.turns),
        round_number=round_number,
        round_limit=round_limit,
    )


@then("consensus is declared")
def then_consensus_declared(decision_context: DecisionContext) -> None:
    assert isinstance(decision_context.outcome, ReachedConsensus)


@then(parsers.parse('the advisory findings include a "{severity}" finding on "{section}"'))
def then_advisory_includes(decision_context: DecisionContext, severity: str, section: str) -> None:
    assert isinstance(decision_context.outcome, ReachedConsensus)
    assert any(
        finding.severity == Severity(severity) and finding.target_section == section
        for finding in decision_context.outcome.advisory_findings
    )


@then("a revision round is requested")
def then_revision_round_requested(decision_context: DecisionContext) -> None:
    assert isinstance(decision_context.outcome, RequestRevision)


@then(parsers.parse("the requested revision carries {count:d} critique(s)"))
def then_revision_carries_critiques(decision_context: DecisionContext, count: int) -> None:
    assert isinstance(decision_context.outcome, RequestRevision)
    assert len(decision_context.outcome.blocking_critiques) == count


@then("a deadlock is declared")
def then_deadlock_declared(decision_context: DecisionContext) -> None:
    assert isinstance(decision_context.outcome, Deadlocked)


@then("the round is reported as incomplete")
def then_round_reported_incomplete(decision_context: DecisionContext) -> None:
    assert isinstance(decision_context.outcome, IncompleteRound)


@dataclass
class ResumeContext:
    root: Path
    herdr: FakeHerdrClient
    store: FakeEventStore
    runner: ReviewRunner
    confirm_calls: list[bool] = field(default_factory=list)
    confirm_response: bool = True
    outcome: RoundOutcome | None = None


@given(
    "a review that deadlocks once and then resolves on the human's confirmation",
    target_fixture="resume_context",
)
def given_resume_setup(tmp_path: Path) -> ResumeContext:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    roster = AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER])
    runner = ReviewRunner(
        herdr=herdr,
        store=store,
        workspace_root=tmp_path,
        specification_id="spec-1",
        roster=roster,
        round_limit=1,
    )
    call_counts = {"dev": 0, "sec": 0}

    def respond(target: str, text: str) -> None:
        del text
        agent = next(name for name, pane in herdr.started_agents.items() if pane == target)
        call_counts[agent] += 1
        result_path = (
            tmp_path / ".roundtable" / "scratch" / str(call_counts[agent]) / f"{agent}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            result_path.write_text(json.dumps({"summary": "the draft"}))
        elif call_counts[agent] == 1:
            result_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "target_section": "Auth",
                                "severity": "blocking",
                                "description": "Auth needs work",
                            }
                        ]
                    }
                )
            )
        else:
            result_path.write_text(json.dumps({"findings": []}))

    herdr.respond = respond
    return ResumeContext(root=tmp_path, herdr=herdr, store=store, runner=runner)


@given("the human will decline to continue")
def given_human_declines(resume_context: ResumeContext) -> None:
    resume_context.confirm_response = False


@when("the run proceeds, confirming resolution after the deadlock")
def when_run_proceeds_confirming(resume_context: ResumeContext) -> None:
    def confirm() -> bool:
        resume_context.confirm_calls.append(True)
        return resume_context.confirm_response

    outcome = resume_context.runner.run(build_context="a widget", confirm=confirm)
    resume_context.outcome = outcome


@then("the resumed run reaches consensus")
def then_resumed_run_reaches_consensus(resume_context: ResumeContext) -> None:
    assert isinstance(resume_context.outcome, ReachedConsensus)


@then("the run ends in the declared deadlock")
def then_run_ends_in_deadlock(resume_context: ResumeContext) -> None:
    assert isinstance(resume_context.outcome, Deadlocked)


@then("the human was asked to confirm exactly once")
def then_confirmed_once(resume_context: ResumeContext) -> None:
    assert len(resume_context.confirm_calls) == 1


@then("the developer is not prompted to draft again after the deadlock")
def then_no_redraft_after_deadlock(resume_context: ResumeContext) -> None:
    drafting_prompts = [
        text
        for _, text in resume_context.herdr.prompts
        if "Draft the specification" in text or "Revise the draft" in text
    ]
    assert len(drafting_prompts) == 1
