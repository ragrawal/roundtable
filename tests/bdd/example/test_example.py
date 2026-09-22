"""Binds example.feature to the shared action-module step definitions.

Step definitions live in tests.bdd.actions.shell / tests.bdd.actions.files and
are registered as fixtures by the wildcard imports in tests/bdd/conftest.py.
This file only binds the feature.

Replace this feature (or add siblings under tests/bdd/<feature_name>/) as the
project grows. See the write-bdd-tests skill for the conventions to follow.
"""

from __future__ import annotations

from pytest_bdd import scenarios

scenarios("example.feature")
