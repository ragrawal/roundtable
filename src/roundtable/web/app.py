"""FastAPI application factory for the roundtable web UI, bound to one workspace."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from roundtable.store import EventStoreProtocol, SqliteEventStore
from roundtable.web.feed_api import build_feed_router
from roundtable.web.roster_api import build_roster_router
from roundtable.workspace import config_path, events_db_path

STATIC_DIR = Path(__file__).parent / "static"


def create_app(workspace_root: Path, *, store: EventStoreProtocol | None = None) -> FastAPI:
    """Build the web UI's FastAPI application for `workspace_root`.

    Args:
        workspace_root: The workspace the roster editor and event feed operate over.
        store: The event store the feed reads from; a real `SqliteEventStore`
            at the workspace's event database path when omitted.

    Returns:
        A FastAPI app with the roster API, event-feed API, and static
        frontend all mounted.
    """
    app = FastAPI(title="roundtable")
    resolved_store = (
        store if store is not None else SqliteEventStore(events_db_path(workspace_root))
    )

    app.include_router(build_roster_router(workspace_root, config_path(workspace_root)))
    app.include_router(build_feed_router(resolved_store))
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
