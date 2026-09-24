"""HTTP and WebSocket endpoints for the live event feed, status, and version browser.

Per `design.md`'s "full replay + client-side dedup instead of a store
cursor" decision: `EventStoreProtocol.replay` returns full history with no
cursor, so the WebSocket handler replays in full on every tick and forwards
only events it has not already sent for that connection, keyed by
`event_id`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from roundtable.events import RoundtableEvent
from roundtable.store import EventStoreProtocol
from roundtable.web.event_feed import filter_events, group_by_round, list_versions
from roundtable.web.status import derive_connection_health, derive_outcome_label

POLL_INTERVAL_SECONDS = 1.0


def _serialize_event(event: RoundtableEvent, round_key: str) -> dict:
    return {**jsonable_encoder(event), "round": round_key}


def _status_payload(events: list[RoundtableEvent], *, connected: bool) -> dict:
    return {
        "outcome_label": derive_outcome_label(events).value,
        "connection_health": derive_connection_health(
            connected=connected, events=events, now=datetime.now(UTC)
        ).value,
    }


def build_feed_router(store: EventStoreProtocol) -> APIRouter:
    """Build the router for the event feed, status, and version-browser endpoints.

    Args:
        store: The event store every route reads from.

    Returns:
        A router exposing REST status/version endpoints and a WebSocket
        event-feed endpoint, all parameterized by `specification_id`.
    """
    router = APIRouter()

    @router.get("/api/specifications/{specification_id}/status")
    def get_status(specification_id: str) -> dict:
        """Return the specification's current outcome label and connection health."""
        events = list(store.replay(specification_id))
        return _status_payload(events, connected=True)

    @router.get("/api/specifications/{specification_id}/versions")
    def get_versions(specification_id: str) -> list[dict]:
        """Return every draft version recorded for the specification, in append order."""
        events = store.replay(specification_id)
        return [jsonable_encoder(version.__dict__) for version in list_versions(events)]

    @router.websocket("/ws/specifications/{specification_id}/events")
    async def stream_events(
        websocket: WebSocket,
        specification_id: str,
        emitter: str | None = None,
        event_type: str | None = None,
        round: str | None = None,
        keyword: str | None = None,
    ) -> None:
        """Push newly recorded events for `specification_id`, deduplicated by `event_id`.

        On every poll tick, replays the specification's full history, drops
        any event already forwarded on this connection, and sends the rest
        alongside the current status. An at-least-once delivery guarantee is
        intentional: the client independently discards anything it has
        already rendered.
        """
        await websocket.accept()
        sent_event_ids: set[str] = set()
        try:
            while True:
                events = list(await asyncio.to_thread(store.replay, specification_id))
                rounds = group_by_round(events)
                filtered = filter_events(
                    events,
                    rounds,
                    emitter=emitter,
                    event_type=event_type,
                    round_number=round,
                    keyword=keyword,
                )
                round_of = {
                    str(event.event_id): round_key
                    for round_key, group in rounds.items()
                    for event in group
                }
                new_events = [
                    event for event in filtered if str(event.event_id) not in sent_event_ids
                ]
                for event in new_events:
                    sent_event_ids.add(str(event.event_id))
                await websocket.send_json(
                    {
                        "events": [
                            _serialize_event(event, round_of[str(event.event_id)])
                            for event in new_events
                        ],
                        "status": _status_payload(events, connected=True),
                    }
                )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            return

    return router
