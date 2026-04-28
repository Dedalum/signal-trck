"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from signal_trck.storage import Store


@pytest.fixture(autouse=True)
def isolated_signal_trck_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``SIGNAL_TRCK_HOME`` at a per-test tmp dir so DB / config are isolated."""
    monkeypatch.setenv("SIGNAL_TRCK_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    """Connected Store backed by a per-test SQLite file."""
    db_path = tmp_path / "test.db"
    store = Store(db_path=db_path)
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
def vcr_config() -> dict:
    """``pytest-recording`` cassette config for adapter tests.

    We strip volatile bits so cassettes are diff-stable across replays.
    """
    return {
        "filter_headers": ["authorization", "x-api-key", "x-cg-demo-api-key"],
        "filter_query_parameters": [],
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
    }
