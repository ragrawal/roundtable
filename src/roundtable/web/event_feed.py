"""Round grouping, filtering, and version-list projections over a specification's event tail.

Grouping uses `CritiqueSubmitted.review_id` and the `discussion_id` carried by
`RevisionRequested`/`ConsensusDeadlocked`/`ConsensusReached`, per the
`roundtable-web-ui` spec's "Event grouping by round number" requirement.
`ArtifactDrafted` carries no round identifier of its own, so it is assigned to
the round it was actually drafted or revised for: the first draft opens round
"1"; a revision's draft joins the round immediately after the
`RevisionRequested` that triggered it, matching `ReviewRunner`'s own
round-numbering (`src/roundtable/orchestration.py`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from roundtable.events import (
    ArtifactDrafted,
    ConsensusDeadlocked,
    ConsensusReached,
    CritiqueSubmitted,
    RevisionRequested,
    RoundtableEvent,
)

FIRST_ROUND = "1"


def group_by_round(events: Sequence[RoundtableEvent]) -> dict[str, list[RoundtableEvent]]:
    """Group `events` by round number, in first-seen round order.

    Args:
        events: A specification's events in append order.

    Returns:
        A mapping from round number (as the string the events themselves
        carry) to the events belonging to that round, in append order.
    """
    groups: dict[str, list[RoundtableEvent]] = defaultdict(list)
    current_round = FIRST_ROUND
    revision_pending = False
    for event in events:
        if isinstance(event, CritiqueSubmitted):
            current_round = event.review_id
            revision_pending = False
        elif isinstance(event, RevisionRequested):
            current_round = event.discussion_id
            revision_pending = True
        elif isinstance(event, ConsensusDeadlocked | ConsensusReached):
            current_round = event.discussion_id
            revision_pending = False
        elif isinstance(event, ArtifactDrafted) and revision_pending:
            current_round = str(int(current_round) + 1)
            revision_pending = False
        groups[current_round].append(event)
    return dict(groups)


def filter_events(
    events: Sequence[RoundtableEvent],
    rounds: dict[str, list[RoundtableEvent]],
    *,
    emitter: str | None = None,
    event_type: str | None = None,
    round_number: str | None = None,
    keyword: str | None = None,
) -> list[RoundtableEvent]:
    """Filter `events` by emitter, event type, round number, and/or a description/content keyword.

    Args:
        events: The events to filter, in append order.
        rounds: `events`' round grouping, as returned by `group_by_round`,
            used to resolve `round_number`.
        emitter: Keep only events from this emitter, if given.
        event_type: Keep only events of this `event_type`, if given.
        round_number: Keep only events in this round, if given.
        keyword: Keep only events whose `description`/`content` field
            contains this substring (case-insensitive), if given.

    Returns:
        The matching events, in their original append order.
    """
    round_of: dict[str, str] = {
        str(event.event_id): round_key for round_key, group in rounds.items() for event in group
    }
    keyword_lower = keyword.lower() if keyword else None
    matched = []
    for event in events:
        if emitter is not None and event.emitter != emitter:
            continue
        if event_type is not None and event.event_type != event_type:
            continue
        if round_number is not None and round_of.get(str(event.event_id)) != round_number:
            continue
        if keyword_lower is not None and keyword_lower not in _searchable_text(event).lower():
            continue
        matched.append(event)
    return matched


def _searchable_text(event: RoundtableEvent) -> str:
    if isinstance(event, ArtifactDrafted):
        return event.content
    if isinstance(event, CritiqueSubmitted):
        return event.finding.description
    if isinstance(event, RevisionRequested):
        return " ".join(critique.description for critique in event.blocking_critiques)
    if isinstance(event, ConsensusDeadlocked):
        return event.trade_offs
    return ""


class ArtifactVersion:
    """One entry in the artifact version browser: an `ArtifactDrafted` event's public fields."""

    def __init__(self, event: ArtifactDrafted) -> None:
        """Wrap `event` for serialization as a version-list entry.

        Args:
            event: The `ArtifactDrafted` event this version summarizes.
        """
        self.version_id = event.version_id
        self.emitter = event.emitter
        self.timestamp = event.timestamp
        self.content = event.content


def list_versions(events: Sequence[RoundtableEvent]) -> list[ArtifactVersion]:
    """Return every `ArtifactDrafted` event in `events`, in append order, as a version entry.

    Args:
        events: A specification's events in append order.

    Returns:
        One `ArtifactVersion` per `ArtifactDrafted` event, oldest first.
    """
    return [ArtifactVersion(event) for event in events if isinstance(event, ArtifactDrafted)]
