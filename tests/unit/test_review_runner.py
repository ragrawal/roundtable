"""Unit tests for roundtable.orchestration.ReviewRunner: the I/O-performing controller."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from roundtable.config import AgentProfile, AgentRoster
from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    ConsensusReached,
    CritiqueFinding,
    CritiqueSubmitted,
    OpposingViewpoint,
    RevisionRequested,
    RoundtableEvent,
    Severity,
)
from roundtable.herdr import AgentState, HerdrError, PaneDirection
from roundtable.orchestration import (
    CritiqueResult,
    Deadlocked,
    DraftFailedError,
    DraftResult,
    EscalationInstruction,
    IncompleteReviewerTurn,
    MissingResultError,
    PaneAllocationError,
    ReachedConsensus,
    ReviewerTurn,
    ReviewRunner,
)

DEVELOPER = AgentProfile(name="dev", role="developer", persona="Write the code.", kind="claude")
SECURITY_REVIEWER = AgentProfile(
    name="sec", role="security reviewer", persona="Look for vulnerabilities.", kind="claude"
)
PM_REVIEWER = AgentProfile(name="pm", role="product manager", persona="Check scope.", kind="codex")
ROSTER = AgentRoster(agents=[DEVELOPER, SECURITY_REVIEWER, PM_REVIEWER])


class FakeEventStore:
    """In-memory stand-in for `EventStoreProtocol`."""

    def __init__(self) -> None:
        self.events: list[RoundtableEvent] = []

    def append(self, event: RoundtableEvent) -> None:
        self.events.append(event)

    def replay(self, specification_id: str) -> Sequence[RoundtableEvent]:
        return [e for e in self.events if e.specification_id == specification_id]

    def latest_of_type(self, specification_id: str, event_type: type) -> Any:
        matches = [
            e
            for e in self.events
            if e.specification_id == specification_id and isinstance(e, event_type)
        ]
        return matches[-1] if matches else None


class FakeHerdrClient:
    """In-memory stand-in for `HerdrClientProtocol` with configurable failure injection."""

    def __init__(self) -> None:
        self._next_pane_id = 1
        self.opened_panes: list[str] = []
        self.closed_panes: list[str] = []
        self.started_agents: dict[str, str] = {}
        self.prompts: list[tuple[str, str]] = []
        self.fail_split_after: int | None = None
        self.fail_prompt_for: set[str] = set()
        self.respond: Callable[[str, str], None] | None = None

    def pane_split(
        self,
        *,
        pane: str | None = None,
        direction: PaneDirection | None = None,
        cwd: str | None = None,
    ) -> str:
        if self.fail_split_after is not None and len(self.opened_panes) >= self.fail_split_after:
            raise HerdrError("simulated pane_split failure")
        pane_id = f"pane-{self._next_pane_id}"
        self._next_pane_id += 1
        self.opened_panes.append(pane_id)
        return pane_id

    def pane_close(self, pane_id: str) -> None:
        self.closed_panes.append(pane_id)

    def agent_start(
        self, name: str, *, kind: str, pane: str, timeout_ms: int | None = None
    ) -> None:
        self.started_agents[name] = pane

    def agent_prompt(
        self,
        target: str,
        text: str,
        *,
        wait: bool = False,
        until: Sequence[AgentState] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if target in self.fail_prompt_for:
            raise HerdrError(f"simulated agent_prompt failure for {target}")
        self.prompts.append((target, text))
        if self.respond is not None:
            self.respond(target, text)
        return {}

    def agent_read(
        self, target: str, *, source: str | None = None, lines: int | None = None
    ) -> dict[str, Any]:
        return {"text": ""}


def _draft(version_id: str = "abc123", content: str = "the draft content") -> ArtifactDrafted:
    return ArtifactDrafted(
        timestamp=datetime.now(UTC),
        specification_id="spec-1",
        emitter="dev",
        version_id=version_id,
        content=content,
    )


def _init_git_repo(path: Path) -> None:
    run_kwargs = {"cwd": path, "check": True, "capture_output": True, "text": True}
    subprocess.run(["git", "init"], **run_kwargs)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.email", "test@example.com"], **run_kwargs)  # noqa: S603, S607
    subprocess.run(["git", "config", "user.name", "Test"], **run_kwargs)  # noqa: S603, S607


def _runner(
    tmp_path: Path, herdr: FakeHerdrClient | None = None, store: FakeEventStore | None = None
) -> ReviewRunner:
    return ReviewRunner(
        herdr=herdr or FakeHerdrClient(),
        store=store or FakeEventStore(),
        workspace_root=tmp_path,
        specification_id="spec-1",
        roster=ROSTER,
        round_limit=3,
    )


def test_allocate_panes_gives_every_roster_agent_its_own_pane(tmp_path: Path) -> None:
    herdr = FakeHerdrClient()
    runner = _runner(tmp_path, herdr=herdr)

    runner.allocate_panes()

    assert set(runner.panes) == {"dev", "sec", "pm"}
    assert len(set(runner.panes.values())) == 3
    assert herdr.started_agents == runner.panes


def test_allocate_panes_tears_down_already_allocated_panes_on_mid_roster_failure(
    tmp_path: Path,
) -> None:
    herdr = FakeHerdrClient()
    herdr.fail_split_after = 2
    runner = _runner(tmp_path, herdr=herdr)

    with pytest.raises(PaneAllocationError) as excinfo:
        runner.allocate_panes()

    assert excinfo.value.agent_name == "pm"
    assert herdr.closed_panes == herdr.opened_panes
    assert runner.panes == {}


def test_read_result_returns_a_well_formed_result(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    result_path = runner._result_path(1, "dev")  # noqa: SLF001
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"summary": "the draft"}')

    result = runner._read_result("dev", result_path, DraftResult)  # noqa: SLF001

    assert isinstance(result, DraftResult)
    assert result.summary == "the draft"


def test_read_result_ignores_trailing_text_after_the_json_value(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    result_path = runner._result_path(1, "sec")  # noqa: SLF001
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"findings": []}\nEOF\npython -m json.tool some/other/file.json\n')

    result = runner._read_result("sec", result_path, CritiqueResult)  # noqa: SLF001

    assert isinstance(result, CritiqueResult)
    assert result.findings == []


def test_read_result_raises_missing_result_error_with_terminal_snapshot(tmp_path: Path) -> None:
    herdr = FakeHerdrClient()
    runner = _runner(tmp_path, herdr=herdr)
    runner.panes = {"dev": "pane-1"}
    result_path = runner._result_path(1, "dev")  # noqa: SLF001

    with pytest.raises(MissingResultError) as excinfo:
        runner._read_result("dev", result_path, DraftResult)  # noqa: SLF001

    assert excinfo.value.agent_name == "dev"
    assert excinfo.value.expected_path == result_path
    assert excinfo.value.terminal_snapshot == ""


def test_scratch_directory_retains_round_files_after_the_round_ends(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    result_path = runner._result_path(2, "sec")  # noqa: SLF001
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"findings": []}')

    del runner

    assert result_path.exists()
    assert result_path.read_text() == '{"findings": []}'


def test_run_draft_commits_to_git_and_records_artifact_drafted_referencing_it(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}
    runner._result_path(1, "dev").parent.mkdir(parents=True, exist_ok=True)  # noqa: SLF001
    runner._result_path(1, "dev").write_text('{"summary": "first draft"}')  # noqa: SLF001

    event = runner.run_draft(round_number=1, build_context="build a widget")

    log = subprocess.run(  # noqa: S603, S607
        ["git", "log", "--oneline"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert log.stdout.strip() != ""
    assert isinstance(event, ArtifactDrafted)
    assert event.content == "first draft"
    assert (
        event.version_id
        == subprocess.run(  # noqa: S603, S607
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    assert event in store.events


def test_run_draft_raises_and_starts_no_critique_phase_when_developer_turn_fails(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    herdr.fail_prompt_for = {"pane-1"}
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}

    with pytest.raises(DraftFailedError):
        runner.run_draft(round_number=1, build_context="build a widget")

    assert store.events == []


def _write_critique_result(runner: ReviewRunner, round_number: int, agent: str, text: str) -> None:
    path = runner._result_path(round_number, agent)  # noqa: SLF001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"findings": [{{"target_section": "Intro", "severity": "major", '
        f'"description": {text!r}}}]}}'.replace("'", '"')
    )


def test_run_critique_round_isolates_each_reviewer_prompt_from_the_others_findings(
    tmp_path: Path,
) -> None:
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}
    _write_critique_result(runner, 1, "sec", "security finding text")
    _write_critique_result(runner, 1, "pm", "product finding text")

    turns = runner.run_critique_round(round_number=1, draft=_draft())

    assert all(isinstance(turn, ReviewerTurn) for turn in turns)
    prompts_by_target = dict(herdr.prompts)
    assert "product finding text" not in prompts_by_target["pane-2"]
    assert "security finding text" not in prompts_by_target["pane-3"]


def test_run_critique_round_records_one_critique_submitted_event_per_finding(
    tmp_path: Path,
) -> None:
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}
    _write_critique_result(runner, 1, "sec", "security finding text")
    _write_critique_result(runner, 1, "pm", "product finding text")

    runner.run_critique_round(round_number=1, draft=_draft())

    submitted = [e for e in store.events if isinstance(e, CritiqueSubmitted)]
    assert len(submitted) == 2
    assert {e.finding.description for e in submitted} == {
        "security finding text",
        "product finding text",
    }
    assert all(e.finding.severity == Severity.MAJOR for e in submitted)


def test_run_critique_round_reports_incomplete_turn_for_a_failed_reviewer(tmp_path: Path) -> None:
    herdr = FakeHerdrClient()
    herdr.fail_prompt_for = {"pane-2"}
    runner = _runner(tmp_path, herdr=herdr)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}
    _write_critique_result(runner, 1, "pm", "product finding text")

    turns = runner.run_critique_round(round_number=1, draft=_draft())

    turns_by_reviewer = {
        turn.reviewer: turn
        for turn in turns
        if isinstance(turn, (ReviewerTurn, IncompleteReviewerTurn))
    }
    assert isinstance(turns_by_reviewer["sec"], IncompleteReviewerTurn)
    assert isinstance(turns_by_reviewer["pm"], ReviewerTurn)


def test_run_revision_records_revision_requested_with_every_blocking_critique(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    runner.panes = {"dev": "pane-1", "sec": "pane-2", "pm": "pane-3"}
    blocking = (
        CritiqueFinding(
            target_section="Auth", severity=Severity.BLOCKING, description="Missing check."
        ),
        CritiqueFinding(
            target_section="Tests", severity=Severity.BLOCKING, description="No coverage."
        ),
    )
    runner._result_path(2, "dev").parent.mkdir(parents=True, exist_ok=True)  # noqa: SLF001
    runner._result_path(2, "dev").write_text('{"summary": "revised draft"}')  # noqa: SLF001

    event = runner.run_revision(round_number=1, blocking_critiques=blocking)

    revision_requested = next(e for e in store.events if isinstance(e, RevisionRequested))
    assert tuple(revision_requested.blocking_critiques) == blocking
    prompt_text = herdr.prompts[-1][1]
    assert "Missing check." in prompt_text
    assert "No coverage." in prompt_text
    assert isinstance(event, ArtifactDrafted)
    assert event.content == "revised draft"


def _agent_for_pane(runner: ReviewRunner, pane_id: str) -> str:
    return next(name for name, pane in runner.panes.items() if pane == pane_id)


def test_run_reaches_consensus_and_records_consensus_reached(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    call_counts = {"dev": 0, "sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        call_counts[agent] += 1
        path = runner._result_path(call_counts[agent], agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": f"draft round {call_counts[agent]}"}))
        else:
            path.write_text(json.dumps({"findings": []}))

    herdr.respond = respond

    outcome = runner.run(build_context="build a widget")

    assert isinstance(outcome, ReachedConsensus)
    assert any(isinstance(e, ConsensusReached) for e in store.events)
    assert not any(isinstance(e, ConsensusDeadlocked) for e in store.events)
    assert set(herdr.closed_panes) == set()
    assert set(runner.panes) == {"dev", "sec", "pm"}


def test_run_exhausts_round_limit_and_records_consensus_deadlocked(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = _runner(tmp_path, herdr=herdr, store=store)
    call_counts = {"dev": 0, "sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        call_counts[agent] += 1
        path = runner._result_path(call_counts[agent], agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": f"draft round {call_counts[agent]}"}))
        else:
            path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "target_section": "Auth",
                                "severity": "blocking",
                                "description": f"{agent} objects",
                            }
                        ]
                    }
                )
            )

    herdr.respond = respond

    outcome = runner.run(build_context="build a widget")

    assert isinstance(outcome, Deadlocked)
    assert any(isinstance(e, ConsensusDeadlocked) for e in store.events)
    assert not any(isinstance(e, ConsensusReached) for e in store.events)
    assert set(herdr.closed_panes) == set()
    assert set(runner.panes) == {"dev", "sec", "pm"}


def test_run_failure_leaves_every_allocated_pane_open(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    runner = _runner(tmp_path, herdr=herdr)
    # FakeHerdrClient assigns pane ids sequentially in roster order (dev first).
    herdr.fail_prompt_for = {"pane-1"}

    with pytest.raises(DraftFailedError):
        runner.run(build_context="build a widget")

    assert herdr.closed_panes == []
    assert set(runner.panes) == {"dev", "sec", "pm"}


def test_build_escalation_reports_pane_and_attach_instruction_without_selecting_a_position(
    tmp_path: Path,
) -> None:
    herdr = FakeHerdrClient()
    runner = _runner(tmp_path, herdr=herdr)
    runner.allocate_panes()
    outcome = Deadlocked(
        target_section="Auth",
        opposing_viewpoints=(
            OpposingViewpoint(agent="sec", position="Must encrypt at rest."),
            OpposingViewpoint(agent="pm", position="Encryption breaks the test harness."),
        ),
        trade_offs="sec: Must encrypt at rest.; pm: Encryption breaks the test harness.",
    )

    instructions = runner.build_escalation(outcome)

    assert {i.agent_name for i in instructions} == {"sec", "pm"}
    for instruction in instructions:
        assert isinstance(instruction, EscalationInstruction)
        assert instruction.pane_id == runner.panes[instruction.agent_name]
        assert instruction.attach_instruction != ""
    assert not any("Must encrypt" in i.attach_instruction for i in instructions)
    assert not any("breaks the test harness" in i.attach_instruction for i in instructions)


def test_run_confirm_and_resume_starts_a_new_round_without_redrafting_exempt_from_round_limit(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = ReviewRunner(
        herdr=herdr,
        store=store,
        workspace_root=tmp_path,
        specification_id="spec-1",
        roster=ROSTER,
        round_limit=1,
    )
    dev_prompt_count = 0
    reviewer_call_counts = {"sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        nonlocal dev_prompt_count
        agent = _agent_for_pane(runner, target)
        if agent == "dev":
            dev_prompt_count += 1
            path = runner._result_path(1, "dev")  # noqa: SLF001
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"summary": "the only draft"}))
            return
        reviewer_call_counts[agent] += 1
        round_number = reviewer_call_counts[agent]
        path = runner._result_path(round_number, agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if round_number == 1:
            findings = [
                {
                    "target_section": "Auth",
                    "severity": "blocking",
                    "description": f"{agent} objects",
                }
            ]
        else:
            findings = []
        path.write_text(json.dumps({"findings": findings}))

    herdr.respond = respond
    confirm_calls = []

    def confirm() -> bool:
        confirm_calls.append(True)
        return True

    outcome = runner.run(build_context="build a widget", confirm=confirm)

    assert dev_prompt_count == 1
    assert len(confirm_calls) == 1
    assert isinstance(outcome, ReachedConsensus)
    deadlock_events = [e for e in store.events if isinstance(e, ConsensusDeadlocked)]
    consensus_events = [e for e in store.events if isinstance(e, ConsensusReached)]
    drafted_events = [e for e in store.events if isinstance(e, ArtifactDrafted)]
    assert len(deadlock_events) == 1
    assert len(consensus_events) == 1
    assert len(drafted_events) == 1
    assert consensus_events[0].final_state_id == drafted_events[0].version_id


def test_run_reports_round_draft_critique_and_outcome_in_order(tmp_path: Path) -> None:
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
        round_limit=3,
        report=messages.append,
    )
    call_counts = {"dev": 0, "sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        call_counts[agent] += 1
        path = runner._result_path(call_counts[agent], agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": f"draft round {call_counts[agent]}"}))
        else:
            path.write_text(json.dumps({"findings": []}))

    herdr.respond = respond

    outcome = runner.run(build_context="build a widget")

    assert isinstance(outcome, ReachedConsensus)
    assert messages[0] == "Round 1 started."
    assert messages[1] == "dev is drafting the specification."
    critique_index = messages.index("Reviewers are critiquing the draft.")
    assert critique_index == 2
    assert messages[3].startswith("sec ") or messages[3].startswith("pm ")
    assert messages[4].startswith("sec ") or messages[4].startswith("pm ")
    assert {messages[3], messages[4]} == {
        "sec raised no findings.",
        "pm raised no findings.",
    }
    assert messages[-1] == "Consensus reached; approving reviewers: sec, pm."


def test_run_reports_a_reviewer_finishing_before_the_others_turn_completes(tmp_path: Path) -> None:
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
    pm_may_finish = threading.Event()

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        path = runner._result_path(1, agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": "the draft"}))
            return
        if agent == "pm":
            pm_may_finish.wait(timeout=5)
        path.write_text(json.dumps({"findings": []}))
        if agent == "sec":
            pm_may_finish.set()

    herdr.respond = respond

    runner.run(build_context="build a widget", confirm=lambda: False)

    reviewer_messages = [
        m for m in messages if m in ("sec raised no findings.", "pm raised no findings.")
    ]
    assert reviewer_messages == ["sec raised no findings.", "pm raised no findings."]


def test_run_reports_a_revision_outcome_naming_outstanding_critique_count(tmp_path: Path) -> None:
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
        round_limit=2,
        report=messages.append,
    )
    call_counts = {"dev": 0, "sec": 0, "pm": 0}

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        call_counts[agent] += 1
        path = runner._result_path(call_counts[agent], agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": f"draft round {call_counts[agent]}"}))
        elif call_counts[agent] == 1:
            path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "target_section": "Auth",
                                "severity": "blocking",
                                "description": f"{agent} objects",
                            }
                        ]
                    }
                )
            )
        else:
            path.write_text(json.dumps({"findings": []}))

    herdr.respond = respond

    outcome = runner.run(build_context="build a widget")

    assert isinstance(outcome, ReachedConsensus)
    assert "Revision requested; 2 critique(s) outstanding." in messages
    assert "Round 2 started." in messages
    assert messages.index("Revision requested; 2 critique(s) outstanding.") < messages.index(
        "Round 2 started."
    )
    assert messages.index("Round 2 started.") < messages.index("dev is revising the draft.")


def test_run_decline_ends_the_run_recording_the_deadlock_and_retaining_every_pane(
    tmp_path: Path,
) -> None:
    _init_git_repo(tmp_path)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    runner = ReviewRunner(
        herdr=herdr,
        store=store,
        workspace_root=tmp_path,
        specification_id="spec-1",
        roster=ROSTER,
        round_limit=1,
    )

    def respond(target: str, text: str) -> None:
        agent = _agent_for_pane(runner, target)
        path = runner._result_path(1, agent)  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        if agent == "dev":
            path.write_text(json.dumps({"summary": "the only draft"}))
        else:
            findings = [
                {
                    "target_section": "Auth",
                    "severity": "blocking",
                    "description": f"{agent} objects",
                }
            ]
            path.write_text(json.dumps({"findings": findings}))

    herdr.respond = respond

    outcome = runner.run(build_context="build a widget", confirm=lambda: False)

    assert isinstance(outcome, Deadlocked)
    assert any(isinstance(e, ConsensusDeadlocked) for e in store.events)
    contested_agents = {vp.agent for vp in outcome.opposing_viewpoints}
    assert contested_agents == {"sec", "pm"}
    assert set(runner.panes) == {"dev", "sec", "pm"}
    assert herdr.closed_panes == []
