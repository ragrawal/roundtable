"""Run lifecycle status: two independent, always-defined signals over an event tail.

Per the `roundtable-web-ui` spec's "Run lifecycle status" requirement: an
**outcome label** derived solely from the recorded event tail, and a
**connection health** derived solely from the live transport and event
recency. Neither signal ever overrides or hides the other; `consensus
reached` is the only outcome label treated as reliably terminal.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from roundtable.events import ConsensusDeadlocked, ConsensusReached, RoundtableEvent

DEFAULT_STALENESS_TIMEOUT = timedelta(seconds=30)


class OutcomeLabel(StrEnum):
    """The outcome label derived from a specification's event tail."""

    NO_HISTORY = "no history yet (may be drafting)"
    IN_PROGRESS = "in progress (estimated)"
    DEADLOCKED = "deadlocked (may still be active)"
    CONSENSUS_REACHED = "consensus reached"


class ConnectionHealth(StrEnum):
    """The connection health derived from the live transport and event recency."""

    LIVE = "live"
    STALE = "stale"
    DISCONNECTED = "disconnected"


def derive_outcome_label(events: Sequence[RoundtableEvent]) -> OutcomeLabel:
    """Derive the outcome label from `events`, the specification's full event tail.

    Args:
        events: The specification's recorded events in append order, as
            returned by `EventStoreProtocol.replay`.

    Returns:
        `NO_HISTORY` if `events` is empty; `CONSENSUS_REACHED` if the last
        event is `ConsensusReached`; `DEADLOCKED` if the last event is
        `ConsensusDeadlocked`; otherwise `IN_PROGRESS`.
    """
    if not events:
        return OutcomeLabel.NO_HISTORY
    last = events[-1]
    if isinstance(last, ConsensusReached):
        return OutcomeLabel.CONSENSUS_REACHED
    if isinstance(last, ConsensusDeadlocked):
        return OutcomeLabel.DEADLOCKED
    return OutcomeLabel.IN_PROGRESS


def derive_connection_health(
    *,
    connected: bool,
    events: Sequence[RoundtableEvent],
    now: datetime,
    staleness_timeout: timedelta = DEFAULT_STALENESS_TIMEOUT,
) -> ConnectionHealth:
    """Derive connection health from transport liveness and event recency.

    Args:
        connected: Whether the live transport to the backend is currently up.
        events: The specification's recorded events in append order.
        now: The current time, compared against the most recent event's timestamp.
        staleness_timeout: How long since the last event before a connected
            transport is considered stale.

    Returns:
        `DISCONNECTED` if `connected` is false, regardless of event state.
        Otherwise `LIVE` if there are no events yet, or the most recent event
        arrived within `staleness_timeout`; `STALE` otherwise. Staleness is
        never evaluated against an empty event list.
    """
    if not connected:
        return ConnectionHealth.DISCONNECTED
    if not events:
        return ConnectionHealth.LIVE
    if now - events[-1].timestamp > staleness_timeout:
        return ConnectionHealth.STALE
    return ConnectionHealth.LIVE
