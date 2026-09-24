"""Event envelope and payload models recorded by the event store.

Every event is a `RoundtableEvent`: a discriminated union of payload models
that each carry the shared `EventEnvelope` fields plus their own required
data. Validation happens once, at construction, per `event-store`'s
"validation precedes persistence" requirement — there is no separate
validate-then-write step downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Severity(StrEnum):
    """Severity of a single critique finding, gating whether it blocks consensus."""

    BLOCKING = "blocking"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class EventEnvelope(BaseModel):
    """Fields shared by every recorded event, regardless of its payload type."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4, description="Unique identifier for this event.")
    timestamp: datetime = Field(..., description="When the event occurred.")
    specification_id: str = Field(
        ..., description="Identifier of the specification under review this event belongs to."
    )
    emitter: str = Field(
        ..., description="Name of the agent or framework component that produced this event."
    )


class CritiqueFinding(BaseModel):
    """A single reviewer finding, referenced by a critique or a revision request."""

    model_config = ConfigDict(extra="forbid")

    target_section: str = Field(
        ..., description="The section of the artifact this finding targets."
    )
    severity: Severity = Field(..., description="How severe this finding is.")
    description: str = Field(..., description="Description of the issue raised.")
    suggested_patch: str | None = Field(
        default=None, description="An optional suggested fix for the issue."
    )


class OpposingViewpoint(BaseModel):
    """One agent's position in a deadlocked disagreement."""

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(..., description="Name of the agent holding this position.")
    position: str = Field(..., description="The position this agent holds.")


class ArtifactDrafted(EventEnvelope):
    """Recorded when a developer agent's draft is accepted and committed.

    `content` is always a short summary, never the full artifact: for a
    spec-phase draft, the real content lives in the `openspec/changes/`
    files committed alongside it; for a code-phase draft, it is the
    committed diff. `version_id`, not `content`, is the canonical reference
    for the complete state.
    """

    event_type: Literal["ArtifactDrafted"] = "ArtifactDrafted"
    version_id: str = Field(
        ..., description="Git state identifier (commit SHA) of the committed draft."
    )
    content: str = Field(
        ...,
        description="Reviewer-facing summary of the draft, suitable for inclusion in a prompt.",
    )


class CritiqueSubmitted(EventEnvelope):
    """Recorded once per critique finding a reviewer raises against a draft."""

    event_type: Literal["CritiqueSubmitted"] = "CritiqueSubmitted"
    review_id: str = Field(
        ..., description="Identifier of the review round this critique belongs to."
    )
    finding: CritiqueFinding = Field(..., description="The critique finding itself.")


class RevisionRequested(EventEnvelope):
    """Recorded when a round ends with blocking critiques and revision is requested."""

    event_type: Literal["RevisionRequested"] = "RevisionRequested"
    discussion_id: str = Field(
        ..., description="Identifier correlating this revision request to its critique round."
    )
    blocking_critiques: list[CritiqueFinding] = Field(
        ..., description="Every blocking critique raised in the round that triggered this revision."
    )


class ConsensusDeadlocked(EventEnvelope):
    """Recorded when a run cannot reach consensus within its round limit."""

    event_type: Literal["ConsensusDeadlocked"] = "ConsensusDeadlocked"
    discussion_id: str = Field(
        ..., description="Identifier correlating this deadlock to its round."
    )
    target_section: str = Field(..., description="The contested section of the artifact.")
    opposing_viewpoints: list[OpposingViewpoint] = Field(
        ..., description="Each opposing position and the agent that holds it."
    )
    trade_offs: str = Field(..., description="The trade-offs between the opposing positions.")


class ConsensusReached(EventEnvelope):
    """Recorded when every reviewer completes a round with no blocking critiques."""

    event_type: Literal["ConsensusReached"] = "ConsensusReached"
    discussion_id: str = Field(
        ..., description="Identifier correlating this consensus to its round."
    )
    approving_reviewers: list[str] = Field(
        ..., description="Names of every reviewer that approved the final draft."
    )
    final_state_id: str = Field(
        ..., description="Git state identifier (commit SHA) of the approved draft."
    )


RoundtableEvent = Annotated[
    ArtifactDrafted
    | CritiqueSubmitted
    | RevisionRequested
    | ConsensusDeadlocked
    | ConsensusReached,
    Field(discriminator="event_type"),
]
"""Discriminated union of every event type the store accepts."""

RoundtableEventAdapter: TypeAdapter[RoundtableEvent] = TypeAdapter(RoundtableEvent)
"""Validates raw event data (dict or JSON bytes) into its concrete payload type."""
