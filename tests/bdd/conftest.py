"""Shared fixtures for this project's pytest-bdd suite.

Step definitions live in tests.bdd.actions.* modules, with @given/@when/@then
applied directly on the functions. Importing those modules here (a conftest.py,
which pytest scans directly for fixtures) is what registers them with pytest --
pytest-bdd's decorators inject each step's fixture into the module where the
decorator is literally written, so a plain import elsewhere would not register
it. See tests/bdd/actions/shell.py and tests/bdd/actions/files.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.bdd.actions.files import *  # noqa: E402,F403
from tests.bdd.actions.shell import *  # noqa: E402,F403

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def project_root() -> Path:
    """The root of this project (where pyproject.toml lives)."""
    return PROJECT_ROOT
