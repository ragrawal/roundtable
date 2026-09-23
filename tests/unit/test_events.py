"""Unit tests for roundtable.events: envelope, severity, payloads, discriminated union."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    ConsensusReached,
    CritiqueFinding,
    CritiqueSubmitted,
    OpposingViewpoint,
    RevisionRequested,
    RoundtableEventAdapter,
    Severity,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

ENVELOPE_FIELDS = {
    "timestamp": NOW,
    "specification_id": "spec-1",
    "emitter": "developer",
}


def _finding(**overrides: object) -> dict:
    base = {
        "target_section": "Requirement: Foo",
        "severity": Severity.BLOCKING,
        "description": "Missing edge case.",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("missing_field", sorted(ENVELOPE_FIELDS))
def test_envelope_missing_field_is_rejected(missing_field: str) -> None:
    fields = {k: v for k, v in ENVELOPE_FIELDS.items() if k != missing_field}
    with pytest.raises(ValidationError) as excinfo:
        ArtifactDrafted(**fields, version_id="abc123", content="draft text")
    assert missing_field in str(excinfo.value)


@pytest.mark.parametrize(
    "severity",
    [Severity.BLOCKING, Severity.MAJOR, Severity.MINOR, Severity.INFO],
    ids=lambda s: s.value,
)
def test_severity_accepts_permitted_values(severity: Severity) -> None:
    finding = CritiqueFinding(**_finding(severity=severity))
    assert finding.severity is severity


def test_severity_rejects_out_of_set_value() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CritiqueFinding(**_finding(severity="catastrophic"))
    message = str(excinfo.value)
    assert "severity" in message
    for permitted in ("blocking", "major", "minor", "info"):
        assert permitted in message


PAYLOAD_CASES = [
    pytest.param(
        ArtifactDrafted,
        {**ENVELOPE_FIELDS, "version_id": "abc123", "content": "draft text"},
        "version_id",
        id="ArtifactDrafted",
    ),
    pytest.param(
        CritiqueSubmitted,
        {**ENVELOPE_FIELDS, "review_id": "round-1", "finding": _finding()},
        "review_id",
        id="CritiqueSubmitted",
    ),
    pytest.param(
        RevisionRequested,
        {
            **ENVELOPE_FIELDS,
            "discussion_id": "round-1",
            "blocking_critiques": [_finding()],
        },
        "discussion_id",
        id="RevisionRequested",
    ),
    pytest.param(
        ConsensusDeadlocked,
        {
            **ENVELOPE_FIELDS,
            "discussion_id": "round-3",
            "target_section": "Requirement: Foo",
            "opposing_viewpoints": [
                OpposingViewpoint(agent="security", position="Reject").model_dump()
            ],
            "trade_offs": "Speed vs. safety.",
        },
        "target_section",
        id="ConsensusDeadlocked",
    ),
    pytest.param(
        ConsensusReached,
        {
            **ENVELOPE_FIELDS,
            "discussion_id": "round-2",
            "approving_reviewers": ["security", "product-manager"],
            "final_state_id": "def456",
        },
        "approving_reviewers",
        id="ConsensusReached",
    ),
]


@pytest.mark.parametrize(("model", "valid_fields", "required_field"), PAYLOAD_CASES)
def test_payload_valid_case(model: type, valid_fields: dict, required_field: str) -> None:
    del required_field
    instance = model(**valid_fields)
    assert instance.specification_id == "spec-1"


@pytest.mark.parametrize(("model", "valid_fields", "required_field"), PAYLOAD_CASES)
def test_payload_missing_required_field_is_rejected(
    model: type, valid_fields: dict, required_field: str
) -> None:
    fields = {k: v for k, v in valid_fields.items() if k != required_field}
    with pytest.raises(ValidationError) as excinfo:
        model(**fields)
    assert required_field in str(excinfo.value)


def test_union_rejects_unrecognized_event_type() -> None:
    with pytest.raises(ValidationError) as excinfo:
        RoundtableEventAdapter.validate_python(
            {
                **ENVELOPE_FIELDS,
                "event_type": "SpecAbandoned",
                "version_id": "abc123",
                "content": "draft text",
            }
        )
    assert "SpecAbandoned" in str(excinfo.value)


def test_union_rejects_unexpected_extra_field() -> None:
    with pytest.raises(ValidationError) as excinfo:
        RoundtableEventAdapter.validate_python(
            {
                **ENVELOPE_FIELDS,
                "event_type": "ArtifactDrafted",
                "version_id": "abc123",
                "content": "draft text",
                "hallucinated_field": "surprise",
            }
        )
    assert "hallucinated_field" in str(excinfo.value)


def test_union_dispatches_to_the_matching_payload_type() -> None:
    event = RoundtableEventAdapter.validate_python(
        {
            **ENVELOPE_FIELDS,
            "event_type": "ArtifactDrafted",
            "version_id": "abc123",
            "content": "draft text",
        }
    )
    assert isinstance(event, ArtifactDrafted)
