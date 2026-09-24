"""Advisory-lock protocol for serializing roster saves against `roundtable.toml`.

A roster save holds a non-blocking, process-death-safe POSIX `flock` on a
`roundtable.lock` file beside `roundtable.toml` across its entire
read-validate-write sequence. Lock ownership is never inferred from the lock
file's age or a recorded process id: the kernel releases the lock
automatically when the holding process dies, and that is the only
crash-recovery mechanism this protocol relies on. See `design.md`'s
"advisory-lock protocol for roster saves" decision for why check-then-write
and age/PID-based reclamation were both rejected.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILENAME = "roundtable.lock"


class RosterLockedError(Exception):
    """Raised when a roster save cannot acquire the advisory lock right now.

    The holder is actively alive and mid-save; the caller should tell the
    operator to retry rather than wait or break the lock.
    """


def lock_path(workspace_root: Path) -> Path:
    """Path to `workspace_root`'s roster advisory-lock file."""
    return workspace_root / LOCK_FILENAME


@contextmanager
def roster_lock(workspace_root: Path) -> Iterator[None]:
    """Hold a non-blocking exclusive advisory lock on the workspace's roster file.

    Args:
        workspace_root: The workspace whose `roundtable.lock` to acquire.

    Yields:
        Nothing; the lock is held for the duration of the `with` block.

    Raises:
        RosterLockedError: another process currently holds the lock.
    """
    path = lock_path(workspace_root)
    file_descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RosterLockedError("The roster is being edited elsewhere; try again.") from exc
        try:
            yield
        finally:
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
    finally:
        os.close(file_descriptor)
