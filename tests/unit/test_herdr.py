"""Unit tests for roundtable.herdr.HerdrClient, against a faked subprocess layer."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from roundtable.herdr import (
    DEFAULT_PROMPT_WAIT_TIMEOUT_SECONDS,
    AgentBlockedError,
    AgentPromptStalledError,
    HerdrClient,
    HerdrCommandError,
    HerdrError,
    HerdrNotFoundError,
    HerdrTimeoutError,
    UnsupportedHerdrVersionError,
)

# Recorded verbatim from a live `herdr 0.9.1` server (see design.md's Context section).
API_SNAPSHOT_FIXTURE = (
    '{"id":"cli:api:snapshot","result":{"snapshot":{"agents":[{"agent":"claude",'
    '"agent_status":"working","cwd":"/Users/riteshagrawal/roundtable","focused":true,'
    '"pane_id":"w8:p1","revision":4,"tab_id":"w8:t1","workspace_id":"w8"}],'
    '"protocol":22,"version":"0.9.1"},"type":"session_snapshot"}}'
)

AGENT_LIST_FIXTURE = (
    '{"id":"cli:agent:list","result":{"agents":[{"agent":"claude",'
    '"agent_status":"working","cwd":"/Users/riteshagrawal/roundtable","focused":true,'
    '"pane_id":"w8:p1","revision":4,"tab_id":"w8:t1","workspace_id":"w8"}],'
    '"type":"agent_list"}}'
)

# Recorded verbatim from `herdr agent prompt nonexistent-agent-xyz "hello"`: herdr
# prints a command failure's error envelope to stderr, with exit code 1.
AGENT_NOT_FOUND_FIXTURE = (
    '{"error":{"code":"agent_not_found","message":'
    '"agent target nonexistent-agent-xyz not found"},"id":"cli:agent:prompt"}'
)

# Recorded verbatim from `herdr pane split --cwd /tmp` (missing the required
# --direction flag): a CLI syntax error prints plain-text usage to stderr,
# with no JSON on either stream, and exits 2.
PANE_SPLIT_USAGE_ERROR_FIXTURE = (
    "usage: herdr pane split [<pane_id>|--pane ID|--current] --direction right|down "
    "[--ratio FLOAT] [--cwd PATH] [--env KEY=VALUE] [--right-click herdr|pane] [--focus] "
    "[--no-focus]\n"
)


class _FakeRun:
    """Stand-in for `subprocess.run` that records calls and returns a canned result."""

    def __init__(
        self, stdout: str = "", *, stderr: str = "", returncode: int = 0, delay: float = 0.0
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, cmd: list[str], *, capture_output: bool, text: bool, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"cmd": cmd, "timeout": timeout})
        if self.delay:
            time.sleep(self.delay)
        return subprocess.CompletedProcess(
            cmd, returncode=self.returncode, stdout=self.stdout, stderr=self.stderr
        )


def _patch_run(monkeypatch: pytest.MonkeyPatch, fake: Callable[..., Any]) -> None:
    monkeypatch.setattr("roundtable.herdr.subprocess.run", fake)


def test_invoke_parses_api_snapshot_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, _FakeRun(API_SNAPSHOT_FIXTURE))
    client = HerdrClient()

    result = client._invoke("api", "snapshot")  # noqa: SLF001

    assert result["snapshot"]["protocol"] == 22
    assert result["snapshot"]["version"] == "0.9.1"
    assert result["snapshot"]["agents"][0]["pane_id"] == "w8:p1"


def test_invoke_parses_agent_list_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, _FakeRun(AGENT_LIST_FIXTURE))
    client = HerdrClient()

    result = client._invoke("agent", "list")  # noqa: SLF001

    assert result["agents"][0]["agent"] == "claude"
    assert result["agents"][0]["agent_status"] == "working"


def test_invoke_raises_herdr_not_found_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError

    _patch_run(monkeypatch, raise_not_found)
    client = HerdrClient()

    with pytest.raises(HerdrNotFoundError):
        client._invoke("api", "snapshot")  # noqa: SLF001


def test_invoke_raises_herdr_error_for_non_json_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, _FakeRun("not json"))
    client = HerdrClient()

    with pytest.raises(HerdrError):
        client._invoke("api", "snapshot")  # noqa: SLF001


def test_invoke_raises_herdr_error_for_a_cli_syntax_error_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A syntax error (missing required flag) prints usage text, not JSON, to stderr."""
    _patch_run(monkeypatch, _FakeRun(stderr=PANE_SPLIT_USAGE_ERROR_FIXTURE, returncode=2))
    client = HerdrClient()

    with pytest.raises(HerdrError, match="usage:"):
        client._invoke("pane", "split", "--cwd", "/tmp")  # noqa: SLF001


@pytest.mark.parametrize(
    ("code", "expected_type"),
    [
        pytest.param("agent_blocked", AgentBlockedError, id="agent_blocked"),
        pytest.param("agent_prompt_stalled", AgentPromptStalledError, id="agent_prompt_stalled"),
        pytest.param("timeout", HerdrTimeoutError, id="timeout"),
        pytest.param("agent_not_found", HerdrCommandError, id="unmapped_code"),
    ],
)
def test_invoke_maps_error_codes_to_typed_errors(
    monkeypatch: pytest.MonkeyPatch, code: str, expected_type: type[HerdrCommandError]
) -> None:
    stderr = f'{{"error":{{"code":"{code}","message":"boom"}},"id":"cli:agent:prompt"}}'
    _patch_run(monkeypatch, _FakeRun(stderr=stderr, returncode=1))
    client = HerdrClient()

    with pytest.raises(expected_type) as excinfo:
        client._invoke("agent", "prompt", "dev", "hi")  # noqa: SLF001
    assert excinfo.value.code == code


def test_invoke_raises_agent_not_found_from_recorded_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run(monkeypatch, _FakeRun(stderr=AGENT_NOT_FOUND_FIXTURE, returncode=1))
    client = HerdrClient()

    with pytest.raises(HerdrCommandError, match="not found"):
        client._invoke("agent", "prompt", "nonexistent-agent-xyz", "hello")  # noqa: SLF001


def test_detect_version_parses_version_string(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, _FakeRun("herdr 0.9.1\n"))
    client = HerdrClient()

    assert client.detect_version() == "0.9.1"


def test_assert_supported_version_passes_for_supported_major(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run(monkeypatch, _FakeRun("herdr 0.9.1\n"))
    client = HerdrClient()

    client.assert_supported_version()


def test_assert_supported_version_raises_naming_both_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run(monkeypatch, _FakeRun("herdr 1.2.3\n"))
    client = HerdrClient()

    with pytest.raises(UnsupportedHerdrVersionError) as excinfo:
        client.assert_supported_version()
    assert excinfo.value.detected_version == "1.2.3"
    assert excinfo.value.supported_major == 0
    assert "1.2.3" in str(excinfo.value)
    assert "0" in str(excinfo.value)


def test_pane_split_composes_args_with_pane_direction_and_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun('{"id":"cli:pane:split","result":{"pane":{"pane_id":"w8:p4"}}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    pane_id = client.pane_split(pane="w8:p1", direction="right", cwd="/tmp/x")

    assert pane_id == "w8:p4"
    assert fake.calls[0]["cmd"] == [
        "herdr",
        "pane",
        "split",
        "--pane",
        "w8:p1",
        "--direction",
        "right",
        "--cwd",
        "/tmp/x",
    ]


def test_pane_close_composes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun('{"id":"cli:pane:close","result":{}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.pane_close("w8:p4")

    assert fake.calls[0]["cmd"] == ["herdr", "pane", "close", "w8:p4"]


def test_agent_start_composes_args_with_kind_pane_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun('{"id":"cli:agent:start","result":{}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_start("dev", kind="claude", pane="w8:p2", timeout_ms=5000)

    assert fake.calls[0]["cmd"] == [
        "herdr",
        "agent",
        "start",
        "dev",
        "--kind",
        "claude",
        "--pane",
        "w8:p2",
        "--timeout",
        "5000",
    ]
    assert fake.calls[0]["timeout"] == 5.0


def test_agent_start_requires_a_pane_id() -> None:
    client = HerdrClient()

    with pytest.raises(TypeError):
        client.agent_start("dev", kind="claude")  # type: ignore[call-arg]


def test_agent_prompt_composes_args_with_wait_until_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun('{"id":"cli:agent:prompt","result":{"agent_status":"idle"}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_prompt(
        "dev", "please draft it", wait=True, until=["idle", "blocked"], timeout_ms=1000
    )

    assert fake.calls[0]["cmd"] == [
        "herdr",
        "agent",
        "prompt",
        "dev",
        "please draft it",
        "--wait",
        "--until",
        "idle",
        "--until",
        "blocked",
        "--timeout",
        "1000",
    ]


def test_agent_prompt_wait_enforces_hard_timeout_even_without_caller_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun('{"id":"cli:agent:prompt","result":{}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_prompt("dev", "hi", wait=True)

    assert fake.calls[0]["timeout"] == DEFAULT_PROMPT_WAIT_TIMEOUT_SECONDS


def test_agent_prompt_without_wait_passes_no_hard_timeout_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun('{"id":"cli:agent:prompt","result":{}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_prompt("dev", "hi")

    assert fake.calls[0]["timeout"] is None


def test_agent_wait_composes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun('{"id":"cli:agent:wait","result":{"agent_status":"idle"}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_wait("dev", until=["done"], timeout_ms=2000)

    assert fake.calls[0]["cmd"] == [
        "herdr",
        "agent",
        "wait",
        "dev",
        "--until",
        "done",
        "--timeout",
        "2000",
    ]
    assert fake.calls[0]["timeout"] == 2.0


def test_agent_read_composes_args(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun('{"id":"cli:agent:read","result":{"text":""}}')
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    client.agent_read("dev", source="recent", lines=50)

    assert fake.calls[0]["cmd"] == [
        "herdr",
        "agent",
        "read",
        "dev",
        "--source",
        "recent",
        "--lines",
        "50",
    ]


def test_concurrent_agent_prompt_calls_do_not_block_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay = 0.2
    fake = _FakeRun('{"id":"cli:agent:prompt","result":{}}', delay=delay)
    _patch_run(monkeypatch, fake)
    client = HerdrClient()

    thread_count = 5
    threads = [
        threading.Thread(target=client.agent_prompt, args=(f"reviewer-{i}", "critique it"))
        for i in range(thread_count)
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - started

    assert len(fake.calls) == thread_count
    assert elapsed < delay * thread_count
