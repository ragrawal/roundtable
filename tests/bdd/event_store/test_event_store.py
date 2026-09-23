"""Binds event_store.feature to the shared action-module step definitions."""

from __future__ import annotations

from pytest_bdd import scenarios

scenarios("event_store.feature")
