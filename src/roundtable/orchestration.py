"""Review round decision logic and the runner that drives it against herdr."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from roundtable.config import AgentProfile, AgentRoster
from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    ConsensusReached,
    CritiqueFinding,
    CritiqueSubmitted,
    OpposingViewpoint,
    RevisionRequested,
    Severity,
)
from roundtable.herdr import HerdrClientProtocol, HerdrError
from roundtable.store import EventStoreProtocol


@dataclass(frozen=True)
class ReviewerTurn:
    """A reviewer's completed turn: the critique findings it returned for the round."""

    reviewer: str
    findings: tuple[CritiqueFinding, ...]


@dataclass(frozen=True)
class IncompleteReviewerTurn:
    """A reviewer's turn that failed or timed out before returning findings."""

    reviewer: str
    reason: str


@dataclass(frozen=True)
class ReachedConsensus:
    """Every reviewer completed its turn for the draft with no blocking critique."""

    approving_reviewers: tuple[str, ...]
    final_state_id: str
    advisory_findings: tuple[CritiqueFinding, ...]


@dataclass(frozen=True)
class RequestRevision:
    """One or more blocking critiques were raised; another round is still available."""

    blocking_critiques: tuple[CritiqueFinding, ...]


@dataclass(frozen=True)
class Deadlocked:
    """The round limit was reached with blocking critiques still outstanding."""

    target_section: str
    opposing_viewpoints: tuple[OpposingViewpoint, ...]
    trade_offs: str


@dataclass(frozen=True)
class IncompleteRound:
    """One or more reviewer turns failed or timed out; no outcome can be declared."""

    failed_reviewers: tuple[str, ...]


RoundOutcome = ReachedConsensus | RequestRevision | Deadlocked | IncompleteRound


class ReviewRound:
    """Pure mapping from a round's inputs to its outcome — no I/O, fully table-testable."""

    @staticmethod
    def decide(
        *,
        draft_version: str,
        turns: tuple[ReviewerTurn | IncompleteReviewerTurn, ...],
        round_number: int,
        round_limit: int,
    ) -> RoundOutcome:
        """Decide a round's outcome from its reviewer turns.

        Args:
            draft_version: Git state identifier of the draft under review.
            turns: One entry per reviewer: its findings, or why its turn failed.
            round_number: The round being decided, counting from 1.
            round_limit: The configured maximum number of automatic rounds.

        Returns:
            `IncompleteRound` if any reviewer turn failed; otherwise
            `ReachedConsensus` if no `blocking` critique was raised;
            otherwise `Deadlocked` if `round_number` has reached `round_limit`,
            or `RequestRevision` if a further round is still available.
        """
        incomplete = [turn for turn in turns if isinstance(turn, IncompleteReviewerTurn)]
        if incomplete:
            return IncompleteRound(failed_reviewers=tuple(turn.reviewer for turn in incomplete))

        completed = [turn for turn in turns if isinstance(turn, ReviewerTurn)]
        blocking = [
            (turn.reviewer, finding)
            for turn in completed
            for finding in turn.findings
            if finding.severity == Severity.BLOCKING
        ]

        if not blocking:
            return ReachedConsensus(
                approving_reviewers=tuple(turn.reviewer for turn in completed),
                final_state_id=draft_version,
                advisory_findings=tuple(finding for turn in completed for finding in turn.findings),
            )

        if round_number >= round_limit:
            return ReviewRound._build_deadlock(blocking)

        return RequestRevision(blocking_critiques=tuple(finding for _, finding in blocking))

    @staticmethod
    def _build_deadlock(blocking: list[tuple[str, CritiqueFinding]]) -> Deadlocked:
        target_section = blocking[0][1].target_section
        return Deadlocked(
            target_section=target_section,
            opposing_viewpoints=tuple(
                OpposingViewpoint(agent=reviewer, position=finding.description)
                for reviewer, finding in blocking
            ),
            trade_offs="; ".join(
                f"{reviewer}: {finding.description}" for reviewer, finding in blocking
            ),
        )


class DraftResult(BaseModel):
    """The developer agent's result artifact for a drafting or revision turn."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., description="Reviewer-facing summary of the draft just committed.")


class CritiqueResult(BaseModel):
    """A reviewer agent's result artifact for a critique turn."""

    model_config = ConfigDict(extra="forbid")

    findings: list[CritiqueFinding] = Field(
        ..., description="Every finding this reviewer raised for the round; empty if none."
    )


class RunnerError(Exception):
    """Base class for `ReviewRunner` orchestration failures."""


class PaneAllocationError(RunnerError):
    """Raised when allocating a pane or starting an agent fails partway through the roster."""

    def __init__(self, agent_name: str, reason: str) -> None:
        """Record which agent could not be placed.

        Args:
            agent_name: The roster agent whose pane allocation or startup failed.
            reason: The underlying failure's message.
        """
        self.agent_name = agent_name
        super().__init__(f"Could not allocate a pane for agent {agent_name!r}: {reason}")


class DraftFailedError(RunnerError):
    """Raised when the developer agent's drafting or revision turn does not produce a draft."""


class MissingResultError(RunnerError):
    """Raised when an agent reaches a terminal state but wrote no result artifact."""

    def __init__(self, agent_name: str, expected_path: Path, terminal_snapshot: str) -> None:
        """Record the missing artifact's expected location and a diagnostic snapshot.

        Args:
            agent_name: The agent that finished its turn without a result.
            expected_path: The path the agent was instructed to write its result to.
            terminal_snapshot: A snapshot of the agent's recent terminal output.
        """
        self.agent_name = agent_name
        self.expected_path = expected_path
        self.terminal_snapshot = terminal_snapshot
        super().__init__(
            f"Agent {agent_name!r} finished its turn but no result was found at {expected_path}."
        )


class IncompleteRoundError(RunnerError):
    """Raised when a round cannot be decided because one or more reviewer turns failed."""

    def __init__(self, failed_reviewers: tuple[str, ...]) -> None:
        """Record which reviewers failed to complete their turn.

        Args:
            failed_reviewers: Names of reviewers whose turn failed or timed out.
        """
        self.failed_reviewers = failed_reviewers
        super().__init__(f"Round incomplete; failed reviewers: {', '.join(failed_reviewers)}.")


@dataclass(frozen=True)
class TeardownWarning:
    """A pane close failure encountered during teardown, reported as a secondary warning."""

    agent_name: str
    pane_id: str
    reason: str


@dataclass(frozen=True)
class EscalationInstruction:
    """The pane identifier and attach instruction reported for one contested agent."""

    agent_name: str
    pane_id: str
    attach_instruction: str


@dataclass
class ReviewRunner:
    """Thin, I/O-performing controller that drives a `ReviewRound` state machine over herdr.

    All decision-making is delegated to `ReviewRound.decide`; this class's
    job is prompting agents, reading their results, committing accepted
    drafts to Git, and appending events — the parts of a run that touch the
    outside world.
    """

    herdr: HerdrClientProtocol
    store: EventStoreProtocol
    workspace_root: Path
    specification_id: str
    roster: AgentRoster
    round_limit: int
    session: str | None = None
    turn_timeout_ms: int | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    panes: dict[str, str] = field(default_factory=dict)

    def _scratch_dir(self, round_number: int) -> Path:
        path = self.workspace_root / ".roundtable" / "scratch" / str(round_number)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _result_path(self, round_number: int, agent_name: str) -> Path:
        return self._scratch_dir(round_number) / f"{agent_name}.json"

    def allocate_panes(self) -> None:
        """Allocate one pane per roster agent and start it, recording the name-to-pane mapping.

        Tears down every pane already allocated for this run before raising,
        so a failure partway through the roster leaves nothing dangling.

        Raises:
            PaneAllocationError: a pane could not be split or an agent could
                not be started for one roster agent.
        """
        allocated: dict[str, str] = {}
        for agent in self.roster.agents:
            try:
                pane_id = self.herdr.pane_split(direction="right", cwd=str(self.workspace_root))
                self.herdr.agent_start(agent.name, kind=agent.kind, pane=pane_id)
            except Exception as exc:
                for pane_id in allocated.values():
                    self.herdr.pane_close(pane_id)
                raise PaneAllocationError(agent.name, str(exc)) from exc
            allocated[agent.name] = pane_id
        self.panes = allocated

    def _read_result(self, agent_name: str, path: Path, model: type[BaseModel]) -> BaseModel:
        if not path.exists():
            raise MissingResultError(agent_name, path, self._snapshot(agent_name))
        return model.model_validate_json(path.read_text())

    def _snapshot(self, agent_name: str) -> str:
        try:
            result = self.herdr.agent_read(self.panes[agent_name])
        except HerdrError:
            return ""
        return str(result.get("text", result))

    def _git_commit(self, message: str) -> str:
        run_kwargs = {
            "cwd": self.workspace_root,
            "check": True,
            "capture_output": True,
            "text": True,
        }
        subprocess.run(["git", "add", "-A"], **run_kwargs)  # noqa: S603, S607
        subprocess.run(["git", "commit", "--allow-empty", "-m", message], **run_kwargs)  # noqa: S603, S607
        completed = subprocess.run(["git", "rev-parse", "HEAD"], **run_kwargs)  # noqa: S603, S607
        return completed.stdout.strip()

    def run_draft(self, *, round_number: int, build_context: str) -> ArtifactDrafted:
        """Prompt the developer agent for a first draft, commit it, and record the event.

        Args:
            round_number: The round this draft starts, normally 1.
            build_context: The build description that seeds the drafting prompt.

        Raises:
            DraftFailedError: the developer agent's turn did not produce a draft.
        """
        developer = self.roster.developer
        result_path = self._result_path(round_number, developer.name)
        prompt = (
            f"{developer.persona}\n\nDraft the specification for: {build_context}\n"
            f'Write your result as JSON matching {{"summary": str}} to {result_path}.'
        )
        try:
            self.herdr.agent_prompt(
                self.panes[developer.name], prompt, wait=True, timeout_ms=self.turn_timeout_ms
            )
            result = self._read_result(developer.name, result_path, DraftResult)
        except (HerdrError, MissingResultError) as exc:
            raise DraftFailedError(f"Developer agent's drafting turn failed: {exc}") from exc
        assert isinstance(result, DraftResult)  # narrows the BaseModel return type

        version_id = self._git_commit(f"draft: round {round_number}")
        event = ArtifactDrafted(
            timestamp=self.clock(),
            specification_id=self.specification_id,
            emitter=developer.name,
            version_id=version_id,
            content=result.summary,
        )
        self.store.append(event)
        return event

    def _run_reviewer_turn(
        self, reviewer: AgentProfile, round_number: int, draft: ArtifactDrafted
    ) -> tuple[CritiqueFinding, ...]:
        result_path = self._result_path(round_number, reviewer.name)
        prompt = (
            f"{reviewer.persona}\n\nCritique this draft (version {draft.version_id}):\n"
            f"{draft.content}\n\n"
            f'Write your result as JSON matching {{"findings": [...]}} to {result_path}.'
        )
        self.herdr.agent_prompt(
            self.panes[reviewer.name], prompt, wait=True, timeout_ms=self.turn_timeout_ms
        )
        result = self._read_result(reviewer.name, result_path, CritiqueResult)
        assert isinstance(result, CritiqueResult)  # narrows the BaseModel return type
        return tuple(result.findings)

    def run_critique_round(
        self, *, round_number: int, draft: ArtifactDrafted
    ) -> tuple[ReviewerTurn | IncompleteReviewerTurn, ...]:
        """Prompt every reviewer in parallel and collect one critique set per reviewer.

        Each reviewer's prompt carries only the draft, never another
        reviewer's output, so turns are independent regardless of execution
        order. One `CritiqueSubmitted` event is recorded per finding.

        Args:
            round_number: The round being critiqued.
            draft: The committed draft every reviewer is prompted with.
        """
        reviewers = self.roster.reviewers
        with ThreadPoolExecutor(max_workers=len(reviewers)) as pool:
            futures = {
                pool.submit(self._run_reviewer_turn, reviewer, round_number, draft): reviewer
                for reviewer in reviewers
            }
            results: dict[str, ReviewerTurn | IncompleteReviewerTurn] = {}
            for future, reviewer in futures.items():
                try:
                    findings = future.result()
                except Exception as exc:  # noqa: BLE001
                    results[reviewer.name] = IncompleteReviewerTurn(reviewer.name, reason=str(exc))
                    continue
                for finding in findings:
                    self.store.append(
                        CritiqueSubmitted(
                            timestamp=self.clock(),
                            specification_id=self.specification_id,
                            emitter=reviewer.name,
                            review_id=str(round_number),
                            finding=finding,
                        )
                    )
                results[reviewer.name] = ReviewerTurn(reviewer.name, findings)
        return tuple(results[reviewer.name] for reviewer in reviewers)

    def run_revision(
        self, *, round_number: int, blocking_critiques: tuple[CritiqueFinding, ...]
    ) -> ArtifactDrafted:
        """Record a revision request, prompt the developer to revise, and commit the new draft.

        Args:
            round_number: The round whose blocking critiques triggered this revision.
            blocking_critiques: Every blocking critique raised in that round.
        """
        self.store.append(
            RevisionRequested(
                timestamp=self.clock(),
                specification_id=self.specification_id,
                emitter="framework",
                discussion_id=str(round_number),
                blocking_critiques=list(blocking_critiques),
            )
        )
        developer = self.roster.developer
        next_round = round_number + 1
        result_path = self._result_path(next_round, developer.name)
        critiques_text = "\n".join(
            f"- [{c.severity.value}] {c.target_section}: {c.description}"
            for c in blocking_critiques
        )
        prompt = (
            f"{developer.persona}\n\nRevise the draft to resolve these blocking critiques:\n"
            f"{critiques_text}\n\n"
            f'Write your result as JSON matching {{"summary": str}} to {result_path}.'
        )
        try:
            self.herdr.agent_prompt(
                self.panes[developer.name], prompt, wait=True, timeout_ms=self.turn_timeout_ms
            )
            result = self._read_result(developer.name, result_path, DraftResult)
        except (HerdrError, MissingResultError) as exc:
            raise DraftFailedError(f"Developer agent's revision turn failed: {exc}") from exc
        assert isinstance(result, DraftResult)  # narrows the BaseModel return type

        version_id = self._git_commit(f"revise: round {next_round}")
        event = ArtifactDrafted(
            timestamp=self.clock(),
            specification_id=self.specification_id,
            emitter=developer.name,
            version_id=version_id,
            content=result.summary,
        )
        self.store.append(event)
        return event

    def record_consensus(self, outcome: ReachedConsensus, *, round_number: int) -> ConsensusReached:
        """Record the terminal `ConsensusReached` event for a round that reached consensus."""
        event = ConsensusReached(
            timestamp=self.clock(),
            specification_id=self.specification_id,
            emitter="framework",
            discussion_id=str(round_number),
            approving_reviewers=list(outcome.approving_reviewers),
            final_state_id=outcome.final_state_id,
        )
        self.store.append(event)
        return event

    def record_deadlock(self, outcome: Deadlocked, *, round_number: int) -> ConsensusDeadlocked:
        """Record the terminal `ConsensusDeadlocked` event for a round that could not resolve."""
        event = ConsensusDeadlocked(
            timestamp=self.clock(),
            specification_id=self.specification_id,
            emitter="framework",
            discussion_id=str(round_number),
            target_section=outcome.target_section,
            opposing_viewpoints=list(outcome.opposing_viewpoints),
            trade_offs=outcome.trade_offs,
        )
        self.store.append(event)
        return event

    def build_escalation(self, outcome: Deadlocked) -> tuple[EscalationInstruction, ...]:
        """Report the pane id and attach instruction for each contested agent.

        Names the agents holding the deadlock's opposing positions without
        selecting between them — resolution is left entirely to the human.
        """
        contested = sorted({viewpoint.agent for viewpoint in outcome.opposing_viewpoints})
        session_hint = (
            f"herdr session attach {self.session}" if self.session else "your herdr session"
        )
        return tuple(
            EscalationInstruction(
                agent_name=agent_name,
                pane_id=self.panes[agent_name],
                attach_instruction=f"Attach with: {session_hint} (pane {self.panes[agent_name]}).",
            )
            for agent_name in contested
        )

    def teardown(self, *, retain: frozenset[str] = frozenset()) -> tuple[TeardownWarning, ...]:
        """Close every framework-allocated pane except those in `retain`.

        A close failure is collected rather than raised, so it cannot mask
        the run's real outcome; it is returned for the caller to report as a
        secondary warning.

        Args:
            retain: Agent names whose panes stay open for human escalation.
        """
        warnings: list[TeardownWarning] = []
        remaining: dict[str, str] = {}
        for agent_name, pane_id in self.panes.items():
            if agent_name in retain:
                remaining[agent_name] = pane_id
                continue
            try:
                self.herdr.pane_close(pane_id)
            except Exception as exc:  # noqa: BLE001
                warnings.append(TeardownWarning(agent_name, pane_id, str(exc)))
                remaining[agent_name] = pane_id
        self.panes = remaining
        return tuple(warnings)

    def run(
        self, *, build_context: str, confirm: Callable[[], bool] | None = None
    ) -> tuple[RoundOutcome, tuple[TeardownWarning, ...]]:
        """Run a full review: allocate panes, draft, critique, revise, and terminate.

        On a declared deadlock, reports escalation instructions and, when
        `confirm` is given, blocks on it before resuming: a truthy result
        starts a new critique round against the current draft — exempt from
        the round limit — without re-running the draft phase; a falsy result
        or a missing `confirm` ends the run in the declared deadlock.

        Args:
            build_context: The build description that seeds the first draft.
            confirm: Called to block for human confirmation after a deadlock
                is reported; omit to end the run at the first deadlock.

        Returns:
            The run's terminal outcome and any teardown warnings.

        Raises:
            IncompleteRoundError: a reviewer turn failed or timed out.
        """
        self.allocate_panes()
        retain_agents: frozenset[str] = frozenset()
        final_outcome: RoundOutcome
        try:
            draft = self.run_draft(round_number=1, build_context=build_context)
            round_number = 1
            exempt_next_round = False
            while True:
                effective_limit = round_number + 1 if exempt_next_round else self.round_limit
                exempt_next_round = False
                turns = self.run_critique_round(round_number=round_number, draft=draft)
                outcome = ReviewRound.decide(
                    draft_version=draft.version_id,
                    turns=turns,
                    round_number=round_number,
                    round_limit=effective_limit,
                )

                if isinstance(outcome, IncompleteRound):
                    raise IncompleteRoundError(outcome.failed_reviewers)

                if isinstance(outcome, ReachedConsensus):
                    self.record_consensus(outcome, round_number=round_number)
                    final_outcome = outcome
                    break

                if isinstance(outcome, RequestRevision):
                    draft = self.run_revision(
                        round_number=round_number, blocking_critiques=outcome.blocking_critiques
                    )
                    round_number += 1
                    continue

                self.record_deadlock(outcome, round_number=round_number)
                self.build_escalation(outcome)
                if confirm is None or not confirm():
                    retain_agents = frozenset(vp.agent for vp in outcome.opposing_viewpoints)
                    final_outcome = outcome
                    break

                round_number += 1
                exempt_next_round = True
        finally:
            warnings = self.teardown(retain=retain_agents)
        return final_outcome, warnings
