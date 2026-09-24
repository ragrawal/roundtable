"""Append-only JSONL event store, keyed by specification id.

Events are pre-validated `RoundtableEvent` Pydantic models by the time they
reach `append` — construction is validation, per `AGENTS.md`'s
fail-fast-at-construction convention, so the store never has to defend
against a malformed payload it could still write.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import UUID

from roundtable.events import EventEnvelope, RoundtableEvent, RoundtableEventAdapter

EventT = TypeVar("EventT", bound=EventEnvelope)


class DuplicateEventError(Exception):
    """Raised when an event whose id is already recorded is appended again."""


class EventStoreProtocol(Protocol):
    """Behavior any event store backend must provide.

    A seam for swapping the JSONL implementation for an indexed backend
    (e.g. SQLite) later without changing `ReviewRunner` or `review-command`.
    """

    def append(self, event: RoundtableEvent) -> None:
        """Persist an event, raising `DuplicateEventError` for a repeated id."""
        ...

    def replay(self, specification_id: str) -> Sequence[RoundtableEvent]:
        """Return every event recorded for a specification, in append order."""
        ...

    def latest_of_type(self, specification_id: str, event_type: type[EventT]) -> EventT | None:
        """Return the most recently appended event of `event_type`, or `None`."""
        ...


class JsonlEventStore:
    """Append-only JSONL store with one file per specification id.

    Each specification's events live in their own `<specification_id>.jsonl`
    file under `root`, one JSON object per line in append order. There is no
    operation that modifies or deletes an already-appended line.
    """

    def __init__(self, root: Path) -> None:
        """Open (creating if needed) a store rooted at `root`.

        Args:
            root: Directory holding one `.jsonl` file per specification id.
        """
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._known_ids: dict[str, set[UUID]] = {
            path.stem: {event.event_id for event in self._read_all(path.stem)}
            for path in self._root.glob("*.jsonl")
        }

    def _path_for(self, specification_id: str) -> Path:
        return self._root / f"{specification_id}.jsonl"

    def _read_all(self, specification_id: str) -> list[RoundtableEvent]:
        path = self._path_for(specification_id)
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as handle:
            return [RoundtableEventAdapter.validate_json(line) for line in handle if line.strip()]

    def append(self, event: RoundtableEvent) -> None:
        """Persist `event`, serializing concurrent callers under a lock.

        Args:
            event: The already-validated event to append.

        Raises:
            DuplicateEventError: `event.event_id` was already recorded for
                its specification id.
        """
        with self._lock:
            known = self._known_ids.setdefault(event.specification_id, set())
            if event.event_id in known:
                raise DuplicateEventError(
                    f"Event {event.event_id} is already recorded for "
                    f"specification {event.specification_id!r}."
                )
            line = RoundtableEventAdapter.dump_json(event).decode("utf-8")
            with self._path_for(event.specification_id).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            known.add(event.event_id)

    def replay(self, specification_id: str) -> Sequence[RoundtableEvent]:
        """Return `specification_id`'s events in append order, or `[]` if none exist."""
        return self._read_all(specification_id)

    def latest_of_type(self, specification_id: str, event_type: type[EventT]) -> EventT | None:
        """Return the most recently appended `event_type` event for `specification_id`."""
        matches = [
            event for event in self._read_all(specification_id) if isinstance(event, event_type)
        ]
        return matches[-1] if matches else None


class SqliteEventStore:
    """Append-only SQLite-backed event store, indexed by specification id and event type.

    The indexed alternative to `JsonlEventStore` referenced in this module's
    docstring: every event is one row in a single `events` table, with
    `event_id`, `specification_id`, `event_type`, `emitter`, and `timestamp`
    broken out into their own columns for querying, and the full validated
    event serialized into `payload` so `replay` reconstructs it exactly via
    `RoundtableEventAdapter`. A per-specification `sequence` column preserves
    append order independent of any clock.
    """

    def __init__(self, path: Path) -> None:
        """Open (creating if needed) a SQLite database at `path`.

        Args:
            path: File the database lives at; parent directories are
                created if missing.
        """
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    specification_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    emitter TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_specification_sequence "
                "ON events (specification_id, sequence)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def append(self, event: RoundtableEvent) -> None:
        """Persist `event`, serializing concurrent callers under a lock.

        Args:
            event: The already-validated event to append.

        Raises:
            DuplicateEventError: `event.event_id` was already recorded for
                its specification id.
        """
        payload = RoundtableEventAdapter.dump_json(event).decode("utf-8")
        with self._lock, closing(self._connect()) as connection, connection:
            (next_sequence,) = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE specification_id = ?",
                (event.specification_id,),
            ).fetchone()
            try:
                connection.execute(
                    "INSERT INTO events "
                    "(event_id, specification_id, event_type, emitter, timestamp, "
                    "sequence, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(event.event_id),
                        event.specification_id,
                        event.event_type,
                        event.emitter,
                        event.timestamp.isoformat(),
                        next_sequence,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateEventError(
                    f"Event {event.event_id} is already recorded for "
                    f"specification {event.specification_id!r}."
                ) from exc

    def replay(self, specification_id: str) -> Sequence[RoundtableEvent]:
        """Return `specification_id`'s events in append order, or `[]` if none exist."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM events WHERE specification_id = ? ORDER BY sequence",
                (specification_id,),
            ).fetchall()
        return [RoundtableEventAdapter.validate_json(row[0]) for row in rows]

    def latest_of_type(self, specification_id: str, event_type: type[EventT]) -> EventT | None:
        """Return the most recently appended `event_type` event for `specification_id`."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM events WHERE specification_id = ? AND event_type = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (specification_id, event_type.__name__),
            ).fetchone()
        if row is None:
            return None
        event = RoundtableEventAdapter.validate_json(row[0])
        assert isinstance(event, event_type)  # guaranteed by the event_type column filter
        return event
