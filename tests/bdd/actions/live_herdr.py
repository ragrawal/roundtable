"""Step definitions that drive the real installed herdr binary directly.

Unlike the rest of the BDD suite (which substitutes a fake herdr script or a
fake HerdrClientProtocol implementation), these steps call HerdrClient
against whatever `herdr` binary is actually on PATH, so wire-format drift
between this client and a real herdr install is caught here instead of
surfacing deep inside a live review run. The scenario skips outright when no
supported herdr install is present.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pytest_bdd import given, parsers, then, when

from roundtable.herdr import (
    HerdrClient,
    HerdrCommandError,
    HerdrNotFoundError,
    PaneDirection,
    UnsupportedHerdrVersionError,
)


@given("the real herdr binary is available and supported", target_fixture="herdr_client")
def given_real_herdr_available() -> HerdrClient:
    client = HerdrClient()
    try:
        client.assert_supported_version()
    except HerdrNotFoundError:
        pytest.skip("herdr is not installed on PATH")
    except UnsupportedHerdrVersionError as exc:
        pytest.skip(str(exc))
    return client


@when(
    parsers.parse('a new pane is split "{direction}" in a temporary directory'),
    target_fixture="split_pane_id",
)
def when_pane_split(direction: str, herdr_client: HerdrClient, tmp_dir: Path) -> str:
    return herdr_client.pane_split(direction=cast(PaneDirection, direction), cwd=str(tmp_dir))


@then("a pane id is returned")
def then_pane_id_returned(split_pane_id: str) -> None:
    assert split_pane_id


@then("closing that pane succeeds")
def then_closing_pane_succeeds(herdr_client: HerdrClient, split_pane_id: str) -> None:
    herdr_client.pane_close(split_pane_id)


@when(
    parsers.parse('closing pane "{pane_id}" is attempted'),
    target_fixture="close_attempt_error",
)
def when_closing_unknown_pane(pane_id: str, herdr_client: HerdrClient) -> Exception | None:
    try:
        herdr_client.pane_close(pane_id)
    except HerdrCommandError as exc:
        return exc
    return None


@then("a HerdrCommandError is raised")
def then_herdr_command_error_raised(close_attempt_error: Exception | None) -> None:
    assert isinstance(close_attempt_error, HerdrCommandError)
