"""Unit tests for roundtable.review_command.run_review: spec/code target dispatch."""

from __future__ import annotations

from pathlib import Path

from roundtable.events import ArtifactDrafted, ConsensusReached
from roundtable.review_command import EXIT_CONSENSUS, EXIT_ORCHESTRATION_FAILURE, run_review
from tests.unit.test_review_command import _respond_with, _setup_workspace
from tests.unit.test_review_runner import FakeEventStore, FakeHerdrClient


def test_run_review_spec_target_seeds_the_developer_prompt_with_the_inline_description(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    _respond_with(herdr, tmp_path, sec_findings=[])

    exit_code = run_review(
        workspace_root=tmp_path,
        target="spec",
        specification_id="widget",
        description="a self-sealing stem bolt",
        herdr=herdr,
        store=store,
    )

    assert exit_code == EXIT_CONSENSUS
    dev_prompt = next(text for _, text in herdr.prompts if "Draft the specification" in text)
    assert "a self-sealing stem bolt" in dev_prompt
    assert any(
        isinstance(e, ArtifactDrafted) and e.specification_id == "widget" for e in store.events
    )


def test_run_review_spec_target_without_context_refuses_and_starts_no_agent(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    herdr = FakeHerdrClient()
    store = FakeEventStore()

    exit_code = run_review(
        workspace_root=tmp_path,
        target="spec",
        specification_id="widget",
        herdr=herdr,
        store=store,
    )

    assert exit_code == EXIT_ORCHESTRATION_FAILURE
    assert herdr.opened_panes == []
    assert store.events == []


def test_run_review_spec_target_reads_context_from_a_file(tmp_path: Path) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    herdr = FakeHerdrClient()
    store = FakeEventStore()
    _respond_with(herdr, tmp_path, sec_findings=[])
    context_file = tmp_path / "context.md"
    context_file.write_text("Build a widget that self-destructs on Tuesdays.")

    exit_code = run_review(
        workspace_root=tmp_path,
        target="spec",
        specification_id="widget",
        context_file=context_file,
        herdr=herdr,
        store=store,
    )

    assert exit_code == EXIT_CONSENSUS
    dev_prompt = next(text for _, text in herdr.prompts if "Draft the specification" in text)
    assert "Build a widget that self-destructs on Tuesdays." in dev_prompt


def test_run_review_code_target_before_spec_consensus_refuses_and_starts_no_agent(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    herdr = FakeHerdrClient()
    store = FakeEventStore()

    exit_code = run_review(
        workspace_root=tmp_path,
        target="code",
        specification_id="widget",
        herdr=herdr,
        store=store,
    )

    assert exit_code == EXIT_ORCHESTRATION_FAILURE
    assert herdr.opened_panes == []


def test_run_review_code_target_seeds_the_developer_prompt_from_the_approved_spec(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    store = FakeEventStore()

    spec_herdr = FakeHerdrClient()
    _respond_with(spec_herdr, tmp_path, sec_findings=[])
    spec_exit_code = run_review(
        workspace_root=tmp_path,
        target="spec",
        specification_id="widget",
        description="a self-sealing stem bolt",
        herdr=spec_herdr,
        store=store,
    )
    assert spec_exit_code == EXIT_CONSENSUS
    approved = store.latest_of_type("widget", ConsensusReached)
    assert approved is not None

    code_herdr = FakeHerdrClient()
    _respond_with(code_herdr, tmp_path, sec_findings=[])
    code_exit_code = run_review(
        workspace_root=tmp_path,
        target="code",
        specification_id="widget",
        herdr=code_herdr,
        store=store,
    )

    assert code_exit_code == EXIT_CONSENSUS
    dev_prompt = next(text for _, text in code_herdr.prompts if "Draft the specification" in text)
    assert approved.final_state_id in dev_prompt
    assert "the draft" in dev_prompt  # the approved spec's recorded content

    assert any(
        isinstance(e, ArtifactDrafted) and e.specification_id == "widget:code" for e in store.events
    )
    assert all(
        not (isinstance(e, ArtifactDrafted) and e.specification_id == "widget")
        or e.content == "the draft"
        for e in store.events
    )


def test_run_review_replaying_the_spec_phase_after_a_code_phase_run_returns_only_spec_events(
    tmp_path: Path,
) -> None:
    _setup_workspace(tmp_path, round_limit=1)
    store = FakeEventStore()

    spec_herdr = FakeHerdrClient()
    _respond_with(spec_herdr, tmp_path, sec_findings=[])
    run_review(
        workspace_root=tmp_path,
        target="spec",
        specification_id="widget",
        description="a self-sealing stem bolt",
        herdr=spec_herdr,
        store=store,
    )
    spec_events_before = list(store.replay("widget"))

    code_herdr = FakeHerdrClient()
    _respond_with(code_herdr, tmp_path, sec_findings=[])
    run_review(
        workspace_root=tmp_path,
        target="code",
        specification_id="widget",
        herdr=code_herdr,
        store=store,
    )

    assert list(store.replay("widget")) == spec_events_before
    assert all(e.specification_id == "widget" for e in store.replay("widget"))
    assert all(e.specification_id == "widget:code" for e in store.replay("widget:code"))
