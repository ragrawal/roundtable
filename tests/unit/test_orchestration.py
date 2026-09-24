"""Unit tests for roundtable.orchestration.ReviewRound: pure round decision logic."""

from __future__ import annotations

import pytest

from roundtable.events import CritiqueFinding, Severity
from roundtable.orchestration import (
    Deadlocked,
    IncompleteReviewerTurn,
    IncompleteRound,
    ReachedConsensus,
    RequestRevision,
    ReviewerTurn,
    ReviewRound,
)


def _finding(
    severity: Severity, description: str = "issue", section: str = "Requirement: Foo"
) -> CritiqueFinding:
    return CritiqueFinding(target_section=section, severity=severity, description=description)


@pytest.mark.parametrize(
    ("turns", "round_number", "round_limit", "expected_type"),
    [
        pytest.param(
            (ReviewerTurn("security", ()), ReviewerTurn("qa", ())),
            1,
            3,
            ReachedConsensus,
            id="consensus_with_no_findings",
        ),
        pytest.param(
            (
                ReviewerTurn("security", (_finding(Severity.INFO),)),
                ReviewerTurn("qa", ()),
            ),
            1,
            3,
            ReachedConsensus,
            id="consensus_with_only_info_findings",
        ),
        pytest.param(
            (
                ReviewerTurn("security", (_finding(Severity.BLOCKING),)),
                ReviewerTurn("qa", ()),
            ),
            1,
            3,
            RequestRevision,
            id="revision_on_a_single_blocking_critique",
        ),
        pytest.param(
            (
                ReviewerTurn("security", (_finding(Severity.MAJOR),)),
                ReviewerTurn("qa", ()),
            ),
            1,
            3,
            RequestRevision,
            id="revision_on_a_single_major_critique",
        ),
        pytest.param(
            (
                ReviewerTurn("security", (_finding(Severity.MINOR),)),
                ReviewerTurn("qa", ()),
            ),
            1,
            3,
            RequestRevision,
            id="revision_on_a_single_minor_critique",
        ),
        pytest.param(
            (
                ReviewerTurn("security", (_finding(Severity.BLOCKING),)),
                ReviewerTurn("qa", ()),
            ),
            3,
            3,
            Deadlocked,
            id="deadlock_at_the_round_limit",
        ),
    ],
)
def test_decide_maps_inputs_to_the_correct_outcome(
    turns: tuple[ReviewerTurn, ...],
    round_number: int,
    round_limit: int,
    expected_type: type,
) -> None:
    outcome = ReviewRound.decide(
        draft_version="abc123", turns=turns, round_number=round_number, round_limit=round_limit
    )

    assert isinstance(outcome, expected_type)


def test_consensus_carries_info_finding_as_advisory_without_blocking() -> None:
    info = _finding(Severity.INFO, description="Consider renaming.")
    turns = (ReviewerTurn("security", (info,)), ReviewerTurn("qa", ()))

    outcome = ReviewRound.decide(draft_version="abc123", turns=turns, round_number=1, round_limit=3)

    assert isinstance(outcome, ReachedConsensus)
    assert info in outcome.advisory_findings
    assert outcome.approving_reviewers == ("security", "qa")
    assert outcome.final_state_id == "abc123"


def test_deadlock_names_section_positions_and_trade_offs_for_two_reviewers() -> None:
    security_finding = _finding(
        Severity.BLOCKING, description="Must encrypt at rest.", section="Requirement: Storage"
    )
    qa_finding = _finding(
        Severity.BLOCKING,
        description="Encryption breaks the test harness.",
        section="Requirement: Storage",
    )
    turns = (
        ReviewerTurn("security", (security_finding,)),
        ReviewerTurn("qa", (qa_finding,)),
    )

    outcome = ReviewRound.decide(draft_version="abc123", turns=turns, round_number=3, round_limit=3)

    assert isinstance(outcome, Deadlocked)
    assert outcome.target_section == "Requirement: Storage"
    assert {vp.agent for vp in outcome.opposing_viewpoints} == {"security", "qa"}
    assert {vp.position for vp in outcome.opposing_viewpoints} == {
        "Must encrypt at rest.",
        "Encryption breaks the test harness.",
    }
    assert "security" in outcome.trade_offs
    assert "qa" in outcome.trade_offs


def test_revision_request_carries_every_blocking_critique() -> None:
    security_finding = _finding(Severity.BLOCKING, description="Missing auth check.")
    qa_finding = _finding(Severity.BLOCKING, description="No test coverage.")
    turns = (
        ReviewerTurn("security", (security_finding,)),
        ReviewerTurn("qa", (qa_finding,)),
    )

    outcome = ReviewRound.decide(draft_version="abc123", turns=turns, round_number=1, round_limit=3)

    assert isinstance(outcome, RequestRevision)
    assert outcome.blocking_critiques == (security_finding, qa_finding)


def test_revision_request_carries_critiques_of_mixed_severity() -> None:
    blocking_finding = _finding(Severity.BLOCKING, description="Missing auth check.")
    minor_finding = _finding(Severity.MINOR, description="Rename this variable.")
    turns = (
        ReviewerTurn("security", (blocking_finding,)),
        ReviewerTurn("qa", (minor_finding,)),
    )

    outcome = ReviewRound.decide(draft_version="abc123", turns=turns, round_number=1, round_limit=3)

    assert isinstance(outcome, RequestRevision)
    assert outcome.blocking_critiques == (blocking_finding, minor_finding)


def test_incomplete_round_names_the_failed_reviewer_instead_of_declaring_consensus() -> None:
    turns = (
        ReviewerTurn("security", ()),
        IncompleteReviewerTurn("qa", reason="timed out"),
    )

    outcome = ReviewRound.decide(draft_version="abc123", turns=turns, round_number=1, round_limit=3)

    assert isinstance(outcome, IncompleteRound)
    assert outcome.failed_reviewers == ("qa",)
