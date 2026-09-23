"""Subprocess client for the herdr CLI: panes, agent lifecycle, prompting.

Every call shells out to the `herdr` binary and parses its `{"id", "result"}`
JSON envelope. A successful call prints that envelope to stdout; herdr prints
a failing call's `{"error": {"code", "message"}}` envelope to stderr instead
(exit 1), or plain-text usage with no JSON at all for a CLI syntax error
(exit 2) — `_invoke` checks both streams. The error envelope is translated
into a typed exception per named failure mode, so callers handle
`agent_blocked`, `agent_prompt_stalled`, and `timeout` without inspecting a
generic subprocess error.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from typing import Any, Literal, Protocol

SUPPORTED_MAJOR_VERSION = 0
"""The only herdr major version this client is verified against (`0.9.1`)."""

DEFAULT_PROMPT_WAIT_TIMEOUT_SECONDS = 300.0
"""Hard subprocess-level ceiling for `agent prompt --wait` when no caller timeout is given."""

AgentState = Literal["idle", "working", "blocked", "done", "unknown"]
PaneDirection = Literal["right", "down"]


class HerdrError(Exception):
    """Base class for every error this client raises."""


class HerdrNotFoundError(HerdrError):
    """Raised when the `herdr` executable is not on `PATH`."""


class UnsupportedHerdrVersionError(HerdrError):
    """Raised when the installed `herdr`'s major version is not supported."""

    def __init__(self, detected_version: str, supported_major: int) -> None:
        """Record the detected and supported versions for the caller to report.

        Args:
            detected_version: The version string reported by `herdr --version`.
            supported_major: The major version this client supports.
        """
        self.detected_version = detected_version
        self.supported_major = supported_major
        super().__init__(
            f"Detected herdr version {detected_version!r} is not supported; "
            f"this client requires major version {supported_major}."
        )


class HerdrCommandError(HerdrError):
    """Raised for a herdr command failure, carrying herdr's own error code."""

    def __init__(self, code: str, message: str) -> None:
        """Record herdr's error code and message.

        Args:
            code: herdr's machine-readable error code, e.g. `"agent_blocked"`.
            message: herdr's human-readable error message.
        """
        self.code = code
        super().__init__(message)


class AgentBlockedError(HerdrCommandError):
    """Raised when a prompt is rejected because the target agent is already blocked."""


class AgentPromptStalledError(HerdrCommandError):
    """Raised when an accepted prompt does not reach a working/blocked state promptly."""


class HerdrTimeoutError(HerdrCommandError):
    """Raised when a caller-supplied timeout expires before a terminal state."""


_ERROR_TYPES: dict[str, type[HerdrCommandError]] = {
    "agent_blocked": AgentBlockedError,
    "agent_prompt_stalled": AgentPromptStalledError,
    "timeout": HerdrTimeoutError,
}


def _error_for(code: str, message: str) -> HerdrCommandError:
    return _ERROR_TYPES.get(code, HerdrCommandError)(code, message)


def _seconds(timeout_ms: int | None) -> float | None:
    return timeout_ms / 1000 if timeout_ms is not None else None


class HerdrClientProtocol(Protocol):
    """Behavior `ReviewRunner` needs from a herdr client.

    A seam so orchestration tests can drive a fake herdr layer instead of
    spawning real subprocesses, mirroring `EventStoreProtocol`.
    """

    def pane_split(
        self,
        *,
        pane: str | None = None,
        direction: PaneDirection | None = None,
        cwd: str | None = None,
    ) -> str:
        """Split a pane and return the new pane's id."""
        ...

    def pane_close(self, pane_id: str) -> None:
        """Close the pane identified by `pane_id`."""
        ...

    def agent_start(
        self, name: str, *, kind: str, pane: str, timeout_ms: int | None = None
    ) -> None:
        """Start `kind` agent named `name` in the existing pane `pane`."""
        ...

    def agent_prompt(
        self,
        target: str,
        text: str,
        *,
        wait: bool = False,
        until: Sequence[AgentState] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Submit `text` to `target`, optionally waiting for a terminal state."""
        ...

    def agent_read(
        self, target: str, *, source: str | None = None, lines: int | None = None
    ) -> dict[str, Any]:
        """Read `target`'s terminal output, for diagnostic use only."""
        ...


class HerdrClient:
    """Subprocess client for the herdr CLI.

    Stateless per call: every method spawns its own subprocess and returns
    its own result, so concurrent calls from multiple threads never share
    mutable state and never block one another.
    """

    def __init__(self, binary: str = "herdr") -> None:
        """Create a client that invokes `binary` (default: `herdr` on `PATH`).

        Args:
            binary: Path or name of the herdr executable to invoke.
        """
        self._binary = binary

    def _invoke(self, *args: str, timeout: float | None = None) -> dict[str, Any]:
        try:
            completed = subprocess.run(  # noqa: S603
                [self._binary, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise HerdrNotFoundError(
                f"The {self._binary!r} executable was not found on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HerdrTimeoutError(
                "timeout",
                f"herdr {' '.join(args)} did not complete within {timeout}s.",
            ) from exc

        envelope = self._parse_envelope(completed, args)
        if "error" in envelope:
            error = envelope["error"]
            raise _error_for(error["code"], error["message"])
        return envelope["result"]

    @staticmethod
    def _parse_envelope(
        completed: subprocess.CompletedProcess[str], args: tuple[str, ...]
    ) -> dict[str, Any]:
        """Parse herdr's `{"id", "result"}`/`{"error"}` envelope from `completed`.

        A successful call prints its envelope on stdout; a command failure
        (exit 1) prints the `{"error": ...}` envelope on stderr instead, and
        a CLI syntax error (exit 2) prints plain-text usage on stderr with no
        JSON at all — so both streams must be checked, in that order.
        """
        for stream in (completed.stdout, completed.stderr):
            if not stream.strip():
                continue
            try:
                envelope: dict[str, Any] = json.loads(stream)
            except json.JSONDecodeError:
                continue
            else:
                return envelope
        raise HerdrError(
            f"herdr produced no JSON envelope for {args!r} (exit {completed.returncode}): "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    def detect_version(self) -> str:
        """Return the installed herdr's version string, e.g. `"0.9.1"`.

        Raises:
            HerdrNotFoundError: the herdr executable was not found on `PATH`.
            HerdrError: `herdr --version`'s output does not contain a version.
        """
        try:
            completed = subprocess.run(  # noqa: S603
                [self._binary, "--version"], capture_output=True, text=True
            )
        except FileNotFoundError as exc:
            raise HerdrNotFoundError(
                f"The {self._binary!r} executable was not found on PATH."
            ) from exc

        match = re.search(r"\d+\.\d+\.\d+", completed.stdout)
        if match is None:
            raise HerdrError(
                f"Could not parse a version from herdr --version output: {completed.stdout!r}"
            )
        return match.group(0)

    def assert_supported_version(self) -> None:
        """Raise `UnsupportedHerdrVersionError` unless the installed major version is supported."""
        version = self.detect_version()
        major = int(version.split(".", 1)[0])
        if major != SUPPORTED_MAJOR_VERSION:
            raise UnsupportedHerdrVersionError(version, SUPPORTED_MAJOR_VERSION)

    def pane_split(
        self,
        *,
        pane: str | None = None,
        direction: PaneDirection | None = None,
        cwd: str | None = None,
    ) -> str:
        """Split a pane and return the new pane's id.

        Args:
            pane: The pane to split; the current pane when omitted.
            direction: `"right"` or `"down"`.
            cwd: Working directory for the new pane.
        """
        args = ["pane", "split"]
        if pane is not None:
            args += ["--pane", pane]
        if direction is not None:
            args += ["--direction", direction]
        if cwd is not None:
            args += ["--cwd", cwd]
        result = self._invoke(*args)
        return result["pane"]["pane_id"]

    def pane_close(self, pane_id: str) -> None:
        """Close the pane identified by `pane_id`."""
        self._invoke("pane", "close", pane_id)

    def agent_start(
        self,
        name: str,
        *,
        kind: str,
        pane: str,
        timeout_ms: int | None = None,
    ) -> None:
        """Start `kind` agent named `name` in the existing pane `pane`.

        `pane` is required: `agent start` cannot create a pane itself, it
        must be given one already at an interactive shell prompt.

        Args:
            name: The agent's name within herdr.
            kind: The agent kind to run, e.g. `"claude"` or `"codex"`.
            pane: An existing pane id already at an interactive shell prompt.
            timeout_ms: Startup readiness timeout in milliseconds.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        self._invoke(*args, timeout=_seconds(timeout_ms))

    def agent_prompt(
        self,
        target: str,
        text: str,
        *,
        wait: bool = False,
        until: Sequence[AgentState] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Submit `text` to `target`, optionally waiting for a terminal state.

        When `wait` is set, a hard subprocess-level timeout is always
        enforced — `timeout_ms` when given, otherwise
        `DEFAULT_PROMPT_WAIT_TIMEOUT_SECONDS` — so a stalled herdr call can
        only ever block the calling thread, never indefinitely.

        Args:
            target: The agent name or pane id to prompt.
            text: The prompt text.
            wait: Wait for the first matching state after submission.
            until: States that satisfy `--wait`; herdr's own default applies
                when omitted.
            timeout_ms: Milliseconds to wait before failing with `timeout`.
        """
        args = ["agent", "prompt", target, text]
        if wait:
            args.append("--wait")
        for state in until or ():
            args += ["--until", state]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]

        hard_timeout = (
            _seconds(timeout_ms) or DEFAULT_PROMPT_WAIT_TIMEOUT_SECONDS
            if wait
            else _seconds(timeout_ms)
        )
        return self._invoke(*args, timeout=hard_timeout)

    def agent_wait(
        self,
        target: str,
        *,
        until: Sequence[AgentState] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Wait until `target` reaches one of the requested states.

        Args:
            target: The agent name or pane id to wait on.
            until: States that satisfy the wait; herdr's own default applies
                when omitted.
            timeout_ms: Milliseconds to wait before failing with `timeout`.
        """
        args = ["agent", "wait", target]
        for state in until or ():
            args += ["--until", state]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        return self._invoke(*args, timeout=_seconds(timeout_ms))

    def agent_read(
        self,
        target: str,
        *,
        source: str | None = None,
        lines: int | None = None,
    ) -> dict[str, Any]:
        """Read `target`'s terminal output, for diagnostic use only.

        Args:
            target: The agent name or pane id to read.
            source: `"visible"`, `"recent"`, `"recent-unwrapped"`, or `"detection"`.
            lines: Number of lines to read.
        """
        args = ["agent", "read", target]
        if source is not None:
            args += ["--source", source]
        if lines is not None:
            args += ["--lines", str(lines)]
        return self._invoke(*args)
